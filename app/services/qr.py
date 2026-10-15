"""Minimal QR Code encoder (byte mode, error correction level M, versions 1-10).

Used for the emergency card link so the QR can be drawn on the patient's phone,
printed on a wallet card and shown offline, without a third-party dependency.
Follows ISO/IEC 18004 as implemented in Project Nayuki's reference encoder.
"""

from __future__ import annotations

# Level M, indexed by version (index 0 unused).
_ECC_CODEWORDS_PER_BLOCK = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_NUM_ERROR_CORRECTION_BLOCKS = (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_MAX_VERSION = 10
_ECL_FORMAT_BITS_M = 0


def _num_raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def _num_data_codewords(ver: int) -> int:
    return (
        _num_raw_data_modules(ver) // 8
        - _ECC_CODEWORDS_PER_BLOCK[ver] * _NUM_ERROR_CORRECTION_BLOCKS[ver]
    )


def _reed_solomon_multiply(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _reed_solomon_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _reed_solomon_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _reed_solomon_multiply(root, 0x02)
    return result


def _reed_solomon_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _reed_solomon_multiply(coef, factor)
    return result


def _alignment_positions(ver: int) -> list[int]:
    if ver == 1:
        return []
    numalign = ver // 7 + 2
    step = (ver * 8 + numalign * 3 + 5) // (numalign * 4 - 4) * 2
    result = [ver * 4 + 10 - i * step for i in range(numalign - 1)]
    result.append(6)
    return list(reversed(result))


class _Qr:
    def __init__(self, ver: int) -> None:
        self.ver = ver
        self.size = ver * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def draw_function_patterns(self) -> None:
        for i in range(self.size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        self.draw_finder(3, 3)
        self.draw_finder(self.size - 4, 3)
        self.draw_finder(3, self.size - 4)
        positions = _alignment_positions(self.ver)
        last = len(positions) - 1
        for i, px in enumerate(positions):
            for j, py in enumerate(positions):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue
                self.draw_alignment(px, py)
        self.draw_format_bits(0)
        self.draw_version()

    def draw_finder(self, x: int, y: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.size and 0 <= yy < self.size:
                    dist = max(abs(dx), abs(dy))
                    self.set_function(xx, yy, dist not in (2, 4))

    def draw_alignment(self, x: int, y: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self.set_function(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format_bits(self, mask: int) -> None:
        data = (_ECL_FORMAT_BITS_M << 3) | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412
        size = self.size
        for i in range(6):
            self.set_function(8, i, (bits >> i) & 1 == 1)
        self.set_function(8, 7, (bits >> 6) & 1 == 1)
        self.set_function(8, 8, (bits >> 7) & 1 == 1)
        self.set_function(7, 8, (bits >> 8) & 1 == 1)
        for i in range(9, 15):
            self.set_function(14 - i, 8, (bits >> i) & 1 == 1)
        for i in range(8):
            self.set_function(size - 1 - i, 8, (bits >> i) & 1 == 1)
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, (bits >> i) & 1 == 1)
        self.set_function(8, size - 8, True)

    def draw_version(self) -> None:
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = (self.ver << 12) | rem
        for i in range(18):
            bit = (bits >> i) & 1 == 1
            a = self.size - 11 + i % 3
            b = i // 3
            self.set_function(a, b, bit)
            self.set_function(b, a, bit)

    def draw_codewords(self, data: list[int]) -> None:
        i = 0
        right = self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (self.size - 1 - vert) if upward else vert
                    if not self.is_function[y][x] and i < len(data) * 8:
                        self.modules[y][x] = ((data[i >> 3] >> (7 - (i & 7))) & 1) == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.is_function[y][x]:
                    continue
                if mask == 0:
                    invert = (x + y) % 2 == 0
                elif mask == 1:
                    invert = y % 2 == 0
                elif mask == 2:
                    invert = x % 3 == 0
                elif mask == 3:
                    invert = (x + y) % 3 == 0
                elif mask == 4:
                    invert = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    invert = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    invert = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    invert = ((x + y) % 2 + x * y % 3) % 2 == 0
                if invert:
                    self.modules[y][x] = not self.modules[y][x]

    def penalty(self) -> int:
        size = self.size
        result = 0
        grid = self.modules
        for line_getter in (lambda a, b: grid[a][b], lambda a, b: grid[b][a]):
            for a in range(size):
                run_color = False
                run = 0
                history = [0] * 7
                for b in range(size):
                    color = line_getter(a, b)
                    if color == run_color:
                        run += 1
                        if run == 5:
                            result += 3
                        elif run > 5:
                            result += 1
                    else:
                        _push_history(history, run, size)
                        if not run_color:
                            result += _count_finder_like(history) * 40
                        run_color = color
                        run = 1
                result += _terminate_and_count(history, run_color, run, size) * 40
        for y in range(size - 1):
            for x in range(size - 1):
                color = grid[y][x]
                if color == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                    result += 3
        dark = sum(row.count(True) for row in grid)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += k * 10
        return result


def _push_history(history: list[int], run: int, size: int) -> None:
    if history[0] == 0:
        run += size
    history.pop()
    history.insert(0, run)


def _count_finder_like(history: list[int]) -> int:
    n = history[1]
    core = n > 0 and history[2] == history[4] == history[5] == n and history[3] == n * 3
    left = int(core and history[0] >= n * 4 and history[6] >= n)
    right = int(core and history[6] >= n * 4 and history[0] >= n)
    return left + right


def _terminate_and_count(history: list[int], run_color: bool, run: int, size: int) -> int:
    if run_color:
        _push_history(history, run, size)
        run = 0
    run += size
    _push_history(history, run, size)
    return _count_finder_like(history)


def encode(text: str) -> list[str]:
    """Encode text as a QR matrix: one string per row, '1' dark and '0' light."""
    data = text.encode("utf-8")
    for ver in range(1, _MAX_VERSION + 1):
        count_bits = 8 if ver <= 9 else 16
        needed = 4 + count_bits + len(data) * 8
        if needed <= _num_data_codewords(ver) * 8:
            break
    else:
        raise ValueError("Text too long for the emergency QR code.")
    capacity = _num_data_codewords(ver) * 8
    bits: list[int] = []

    def append(value: int, length: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(length)))

    append(0x4, 4)
    append(len(data), count_bits)
    for byte in data:
        append(byte, 8)
    append(0, min(4, capacity - len(bits)))
    append(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        append(pad, 8)
        pad ^= 0xEC ^ 0x11
    codewords = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]

    numblocks = _NUM_ERROR_CORRECTION_BLOCKS[ver]
    ecc_len = _ECC_CODEWORDS_PER_BLOCK[ver]
    raw = _num_raw_data_modules(ver) // 8
    num_short = numblocks - raw % numblocks
    short_len = raw // numblocks
    divisor = _reed_solomon_divisor(ecc_len)
    blocks: list[list[int]] = []
    k = 0
    for i in range(numblocks):
        dat = codewords[k : k + short_len - ecc_len + (0 if i < num_short else 1)]
        k += len(dat)
        ecc = _reed_solomon_remainder(dat, divisor)
        if i < num_short:
            dat = [*dat, 0]
        blocks.append(dat + ecc)
    interleaved: list[int] = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= num_short:
                interleaved.append(block[i])

    qr = _Qr(ver)
    qr.draw_function_patterns()
    qr.draw_codewords(interleaved)
    best_mask = 0
    best_penalty: int | None = None
    for mask in range(8):
        qr.apply_mask(mask)
        qr.draw_format_bits(mask)
        score = qr.penalty()
        if best_penalty is None or score < best_penalty:
            best_mask, best_penalty = mask, score
        qr.apply_mask(mask)
    qr.apply_mask(best_mask)
    qr.draw_format_bits(best_mask)
    return ["".join("1" if cell else "0" for cell in row) for row in qr.modules]
