#!/usr/bin/env python3
"""Minimal Niimbot B1 driver over USB (CDC-ACM serial, /dev/ttyACM0).

Protocol: 55 55 <cmd> <len> <data...> <xor-checksum> AA AA
(checksum = cmd ^ len ^ data bytes). Based on the public niimprint /
niimbluelib reverse-engineering.
"""
import argparse
import datetime
import struct
import sys
import time

import serial
from PIL import Image, ImageDraw, ImageFont, ImageOps

PORT = "/dev/ttyACM0"
HEAD_PX = 384          # B1 print head: 384 dots (203 dpi, ~48 mm)
ROW_BYTES = HEAD_PX // 8

# request -> expected response command
CMD_CONNECT = 0xC1
CMD_HEARTBEAT = 0xDC
CMD_GET_INFO = 0x40
CMD_GET_RFID = 0x1A
CMD_SET_DENSITY = 0x21
CMD_SET_LABEL_TYPE = 0x23
CMD_PRINT_START = 0x01
CMD_PAGE_START = 0x03
CMD_SET_PAGE_SIZE = 0x13
CMD_SET_QUANTITY = 0x15
CMD_ROW_EMPTY = 0x84
CMD_ROW_BITMAP = 0x85
CMD_PAGE_END = 0xE3
CMD_PRINT_STATUS = 0xA3
CMD_PRINT_END = 0xF3
CMD_ERROR = 0xDB

INFO_KEYS = {
    "density": 1, "speed": 2, "label_type": 3, "language": 6,
    "auto_shutdown": 7, "device_type": 8, "soft_version": 9,
    "battery": 10, "serial": 11, "hard_version": 12,
}

ERRORS = {
    0x01: "cover open", 0x02: "out of paper / no label detected",
    0x03: "low battery", 0x04: "battery exception", 0x05: "user cancelled",
    0x06: "data error", 0x07: "timeout", 0x08: "unsupported label",
    0x09: "wrong label / RFID check failed", 0x0A: "?", 0x0B: "print head overheat",
}


class Packet:
    def __init__(self, cmd, data=b""):
        self.cmd, self.data = cmd, bytes(data)

    def to_bytes(self):
        cs = self.cmd ^ len(self.data)
        for b in self.data:
            cs ^= b
        return (b"\x55\x55" + bytes([self.cmd, len(self.data)]) + self.data
                + bytes([cs]) + b"\xaa\xaa")

    def __repr__(self):
        return f"<{self.cmd:02X} len={len(self.data)} {self.data.hex()}>"


def parse_packets(buf):
    pkts = []
    while True:
        i = buf.find(b"\x55\x55")
        if i < 0:
            return pkts, b""
        if len(buf) < i + 4:
            return pkts, buf[i:]
        cmd, ln = buf[i + 2], buf[i + 3]
        end = i + 4 + ln + 3
        if len(buf) < end:
            return pkts, buf[i:]
        data = buf[i + 4:i + 4 + ln]
        cs = buf[i + 4 + ln]
        tail = buf[i + 5 + ln:end]
        calc = cmd ^ ln
        for b in data:
            calc ^= b
        if tail == b"\xaa\xaa" and cs == calc:
            pkts.append(Packet(cmd, data))
            buf = buf[end:]
        else:
            buf = buf[i + 2:]


class PrinterError(Exception):
    pass


class B1:
    def __init__(self, port=PORT, verbose=False):
        self.ser = serial.Serial(port, 115200, timeout=0.05)
        self.buf = b""
        self.queue = []
        self.verbose = verbose

    def close(self):
        self.ser.close()

    def send(self, pkt):
        if self.verbose:
            print("->", pkt)
        self.ser.write(pkt.to_bytes())
        self.ser.flush()

    def recv(self, timeout=1.0):
        if self.queue:
            return self.queue.pop(0)
        t0 = time.time()
        while time.time() - t0 < timeout:
            chunk = self.ser.read(512)
            if chunk:
                self.buf += chunk
                pkts, self.buf = parse_packets(self.buf)
                self.queue.extend(pkts)
                if self.queue:
                    return self.queue.pop(0)
        return None

    def transceive(self, cmd, data=b"", resp=None, timeout=2.0):
        self.send(Packet(cmd, data))
        t0 = time.time()
        while True:
            left = timeout - (time.time() - t0)
            if left <= 0:
                return None
            p = self.recv(left)
            if p is None:
                return None
            if self.verbose:
                print("<-", p)
            if p.cmd == CMD_ERROR:
                code = p.data[0] if p.data else -1
                raise PrinterError(f"printer error 0x{code:02X}: {ERRORS.get(code, 'unknown')}")
            if resp is None or p.cmd == resp:
                return p

    # ---- queries -------------------------------------------------------
    def connect(self):
        return self.transceive(CMD_CONNECT, b"\x01", 0xC2)

    def heartbeat(self):
        return self.transceive(CMD_HEARTBEAT, b"\x01", 0xDD)

    def get_info(self, key):
        p = self.transceive(CMD_GET_INFO, bytes([key]), CMD_GET_INFO + key)
        if p is None:
            return None
        d = p.data
        if key == INFO_KEYS["serial"]:
            return d.decode(errors="replace")
        if key == INFO_KEYS["soft_version"] or key == INFO_KEYS["hard_version"]:
            return int.from_bytes(d, "big") / 100
        return int.from_bytes(d, "big")

    def get_rfid(self):
        p = self.transceive(CMD_GET_RFID, b"\x01", 0x1B)
        if p is None or not p.data or p.data[0] == 0:
            return None
        d = p.data
        uuid = d[0:8].hex()
        i = 8
        bl = d[i]; i += 1
        barcode = d[i:i + bl].decode(errors="replace"); i += bl
        sl = d[i]; i += 1
        serial_ = d[i:i + sl].decode(errors="replace"); i += sl
        rest = d[i:]
        total = used = typ = None
        if len(rest) >= 5:
            total, used, typ = struct.unpack(">HHB", rest[:5])
        return {"uuid": uuid, "barcode": barcode, "serial": serial_,
                "total_len": total, "used_len": used, "type": typ, "raw": d.hex()}

    def print_status(self):
        p = self.transceive(CMD_PRINT_STATUS, b"\x01", 0xB3, timeout=1.0)
        if p is None:
            return None
        d = p.data
        page = int.from_bytes(d[0:2], "big") if len(d) >= 2 else None
        prog1 = d[2] if len(d) > 2 else None
        prog2 = d[3] if len(d) > 3 else None
        return {"page": page, "progress1": prog1, "progress2": prog2, "raw": d.hex()}

    # ---- printing ------------------------------------------------------
    def print_image(self, img, density=3, label_type=1, copies=1):
        """img: PIL image, width must be HEAD_PX, black = print."""
        if img.width != HEAD_PX:
            raise ValueError(f"image width must be {HEAD_PX}px, got {img.width}")
        rows = img.height
        # pack: 1 bit = black. mode '1' tobytes packs 1 for white, so invert first.
        packed = ImageOps.invert(img.convert("L")).convert("1").tobytes()
        assert len(packed) == rows * ROW_BYTES

        def expect(name, p):
            if p is None:
                raise PrinterError(f"no reply to {name}")
            if self.verbose:
                print(f"   {name} ok: {p}")
            return p

        expect("set_density", self.transceive(CMD_SET_DENSITY, bytes([density]), 0x31))
        expect("set_label_type", self.transceive(CMD_SET_LABEL_TYPE, bytes([label_type]), 0x33))
        p = self.transceive(CMD_PRINT_START, struct.pack(">HH", 1, 0), 0x02)
        if p is None:  # older protocol variant
            p = self.transceive(CMD_PRINT_START, b"\x01", 0x02)
        expect("print_start", p)
        expect("page_start", self.transceive(CMD_PAGE_START, b"\x01", 0x04))
        p = self.transceive(CMD_SET_PAGE_SIZE, struct.pack(">HHH", rows, HEAD_PX, copies), 0x14)
        if p is None:
            p = self.transceive(CMD_SET_PAGE_SIZE, struct.pack(">HH", rows, HEAD_PX), 0x14)
            expect("set_page_size", p)
            expect("set_quantity", self.transceive(CMD_SET_QUANTITY, struct.pack(">H", copies), 0x16))
        else:
            expect("set_page_size", p)

        sent = 0
        y = 0
        while y < rows:
            row = packed[y * ROW_BYTES:(y + 1) * ROW_BYTES]
            # merge identical consecutive rows into a repeat count
            rep = 1
            while y + rep < rows and rep < 255 and packed[(y + rep) * ROW_BYTES:(y + rep + 1) * ROW_BYTES] == row:
                rep += 1
            if not any(row):
                self.send(Packet(CMD_ROW_EMPTY, struct.pack(">HB", y, rep)))
            else:
                seg = HEAD_PX // 3 // 8  # bytes per third of the head
                counts = [min(255, sum(bin(b).count("1") for b in row[k * seg:(k + 1) * seg])) for k in range(3)]
                self.send(Packet(CMD_ROW_BITMAP, struct.pack(">H3BB", y, *counts, rep) + row))
            sent += 1
            y += rep
        if self.verbose:
            print(f"   sent {sent} row packets for {rows} rows")

        expect("page_end", self.transceive(CMD_PAGE_END, b"\x01", 0xE4, timeout=5.0))

        t0 = time.time()
        last = None
        while time.time() - t0 < 30:
            st = self.print_status()
            if st != last and self.verbose:
                print("   status:", st)
            last = st
            if st and st["page"] and st["page"] >= copies and st["progress1"] == 100 and st["progress2"] == 100:
                break
            time.sleep(0.2)
        expect("print_end", self.transceive(CMD_PRINT_END, b"\x01", 0xF4, timeout=5.0))


def make_test_label(rows, density=None):
    img = Image.new("L", (HEAD_PX, rows), 255)
    d = ImageDraw.Draw(img)
    bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    d.rectangle([2, 2, HEAD_PX - 3, rows - 3], outline=0, width=3)
    d.text((HEAD_PX // 2, 20), "NIIMBOT B1", font=bold, fill=0, anchor="mt")
    d.text((HEAD_PX // 2, 68), "USB test print OK", font=small, fill=0, anchor="mt")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if density is not None:
        stamp += f"  density {density}"
    d.text((HEAD_PX // 2, 98), stamp, font=small, fill=0, anchor="mt")
    # gradient bar of stripes to show head coverage
    for x in range(12, HEAD_PX - 12, 8):
        d.rectangle([x, rows - 44, x + 3, rows - 14], fill=0)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=PORT)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    pt = sub.add_parser("test")
    pt.add_argument("--rows", type=int, default=240, help="label length in dots (203 dpi); 240 = 30 mm")
    pt.add_argument("--density", type=int, default=5, help="1..5, printer rejects higher")
    pt.add_argument("--save", help="also save the rendered PNG here")
    pi = sub.add_parser("image")
    pi.add_argument("file")
    pi.add_argument("--density", type=int, default=5, help="1..5, printer rejects higher")
    args = ap.parse_args()

    pr = B1(args.port, verbose=args.verbose)
    try:
        if args.cmd == "info":
            print("connect  :", pr.connect())
            print("heartbeat:", pr.heartbeat())
            for name, key in INFO_KEYS.items():
                print(f"{name:14s}: {pr.get_info(key)}")
            print("rfid     :", pr.get_rfid())
            print("status   :", pr.print_status())
        elif args.cmd == "test":
            pr.connect()
            img = make_test_label(args.rows, args.density)
            if args.save:
                img.save(args.save)
            pr.print_image(img, density=args.density)
            print("done")
        elif args.cmd == "image":
            pr.connect()
            img = Image.open(args.file).convert("L")
            if img.width != HEAD_PX:
                h = round(img.height * HEAD_PX / img.width)
                img = img.resize((HEAD_PX, h), Image.LANCZOS)
            pr.print_image(img.point(lambda v: 255 if v > 128 else 0), density=args.density)
            print("done")
    finally:
        pr.close()


if __name__ == "__main__":
    main()
