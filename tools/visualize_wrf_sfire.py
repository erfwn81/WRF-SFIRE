#!/usr/bin/env python3
"""Create lightweight PNG/GIF previews from the WRF-SFIRE baseline output.

This reader uses the system NetCDF C library through ctypes so the visualization
does not require xarray, netCDF4-python, or matplotlib.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "test/em_fire/hill/wrfout_d01_0001-01-01_00:00:00"
OUTPUT = ROOT / "output/visualizations"
OUTPUT.mkdir(parents=True, exist_ok=True)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(BOLD_PATH if bold else FONT_PATH, size)


class NetCDF:
    NC_NOWRITE = 0
    NC_MAX_VAR_DIMS = 1024

    def __init__(self, path: Path):
        library = ctypes.util.find_library("netcdf")
        if not library:
            raise RuntimeError("System libnetcdf was not found")
        self.lib = ctypes.CDLL(library)
        self.lib.nc_strerror.restype = ctypes.c_char_p
        self.ncid = ctypes.c_int()
        self._check(self.lib.nc_open(str(path).encode(), self.NC_NOWRITE, ctypes.byref(self.ncid)))

    def _check(self, code: int) -> None:
        if code:
            raise RuntimeError(self.lib.nc_strerror(code).decode())

    def close(self) -> None:
        self._check(self.lib.nc_close(self.ncid))

    def shape(self, name: str) -> tuple[int, ...]:
        varid = ctypes.c_int()
        self._check(self.lib.nc_inq_varid(self.ncid, name.encode(), ctypes.byref(varid)))
        ndims = ctypes.c_int()
        self._check(self.lib.nc_inq_varndims(self.ncid, varid, ctypes.byref(ndims)))
        dimids = (ctypes.c_int * ndims.value)()
        self._check(self.lib.nc_inq_vardimid(self.ncid, varid, dimids))
        sizes = []
        for dimid in dimids:
            length = ctypes.c_size_t()
            self._check(self.lib.nc_inq_dimlen(self.ncid, dimid, ctypes.byref(length)))
            sizes.append(length.value)
        return tuple(sizes)

    def read_float(self, name: str, time_index: int = 0) -> np.ndarray:
        varid = ctypes.c_int()
        self._check(self.lib.nc_inq_varid(self.ncid, name.encode(), ctypes.byref(varid)))
        shape = self.shape(name)
        if len(shape) < 2:
            raise ValueError(f"{name} is not a gridded variable: {shape}")
        if time_index < 0:
            time_index += shape[0]
        if not 0 <= time_index < shape[0]:
            raise IndexError(f"Time index {time_index} is outside {name} shape {shape}")
        start = [0] * len(shape)
        count = list(shape)
        start[0] = time_index
        count[0] = 1
        out_shape = shape[1:]
        data = np.empty(int(np.prod(out_shape)), dtype=np.float32)
        start_c = (ctypes.c_size_t * len(start))(*start)
        count_c = (ctypes.c_size_t * len(count))(*count)
        pointer = data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._check(self.lib.nc_get_vara_float(self.ncid, varid, start_c, count_c, pointer))
        return data.reshape(out_shape)


def normalize(values: np.ndarray, low: float | None = None, high: float | None = None) -> np.ndarray:
    good = np.isfinite(values) & (np.abs(values) < 1.0e30)
    if not np.any(good):
        return np.zeros(values.shape, dtype=np.float32)
    lo = float(np.nanpercentile(values[good], 2)) if low is None else low
    hi = float(np.nanpercentile(values[good], 98)) if high is None else high
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def palette(values: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    values = np.clip(values, 0, 1)
    result = np.empty(values.shape + (3,), dtype=np.float32)
    for index in range(len(stops) - 1):
        a, color_a = stops[index]
        b, color_b = stops[index + 1]
        mask = (values >= a) & (values <= b if index == len(stops) - 2 else values < b)
        weight = np.clip((values[mask] - a) / max(b - a, 1e-9), 0, 1)[:, None]
        ca = np.asarray(color_a, dtype=np.float32)
        cb = np.asarray(color_b, dtype=np.float32)
        result[mask] = ca * (1 - weight) + cb * weight
    return np.uint8(np.clip(result, 0, 255))


TERRAIN = [(0.0, (31, 55, 48)), (0.35, (76, 111, 73)), (0.7, (159, 142, 92)), (1.0, (232, 224, 195))]
FIRE = [(0.0, (255, 240, 145)), (0.35, (255, 158, 54)), (0.7, (214, 57, 29)), (1.0, (87, 12, 25))]
TIME = [(0.0, (255, 244, 174)), (0.3, (255, 179, 71)), (0.65, (223, 78, 35)), (1.0, (92, 25, 85))]
ROS = [(0.0, (239, 247, 255)), (0.3, (116, 191, 205)), (0.65, (39, 110, 148)), (1.0, (25, 35, 70))]


def grid_image(rgb: np.ndarray, size: int = 460) -> Image.Image:
    # WRF arrays are indexed south-to-north; flip for north/up display.
    return Image.fromarray(np.flipud(rgb), "RGB").resize((size, size), Image.Resampling.BILINEAR)


def boundary(mask: np.ndarray) -> np.ndarray:
    edge = np.zeros_like(mask, dtype=bool)
    edge[1:, :] |= mask[1:, :] != mask[:-1, :]
    edge[:-1, :] |= mask[:-1, :] != mask[1:, :]
    edge[:, 1:] |= mask[:, 1:] != mask[:, :-1]
    edge[:, :-1] |= mask[:, :-1] != mask[:, 1:]
    return edge & mask


def add_colorbar(canvas: Image.Image, box: tuple[int, int, int, int], stops, minimum: str, maximum: str) -> None:
    x0, y0, x1, y1 = box
    ramp = np.linspace(1, 0, y1 - y0)[:, None]
    ramp = np.repeat(ramp, x1 - x0, axis=1)
    canvas.paste(Image.fromarray(palette(ramp, stops), "RGB"), (x0, y0))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(box, outline=(120, 126, 132), width=1)
    draw.text((x1 + 7, y0 - 8), maximum, fill=(30, 35, 40), font=font(16))
    draw.text((x1 + 7, y1 - 14), minimum, fill=(30, 35, 40), font=font(16))


def panel(canvas: Image.Image, image: Image.Image, x: int, y: int, title: str, subtitle: str, stops=None, min_label="", max_label="") -> None:
    draw = ImageDraw.Draw(canvas)
    draw.text((x, y), title, fill=(22, 32, 42), font=font(25, bold=True))
    draw.text((x, y + 34), subtitle, fill=(76, 86, 96), font=font(17))
    top = y + 65
    canvas.paste(image, (x, top))
    draw.rectangle((x, top, x + image.width, top + image.height), outline=(110, 118, 124), width=2)
    draw.text((x, top + image.height + 8), "west → east", fill=(76, 86, 96), font=font(16))
    if stops:
        add_colorbar(canvas, (x + image.width + 14, top + 18, x + image.width + 34, top + image.height - 18), stops, min_label, max_label)


def create_overview(dataset: NetCDF) -> Path:
    # The stored 420 x 420 arrays include a five-cell halo around the
    # 410 x 410 physical fire patch reported by SFIRE.
    crop = lambda values: values[5:-5, 5:-5]
    terrain = crop(dataset.read_float("ZSF", 0))
    tign = crop(dataset.read_float("TIGN_G", -1))
    level_set = crop(dataset.read_float("LFN", -1))
    ros = crop(dataset.read_float("ROS", -1))
    hfx = crop(dataset.read_float("FGRNHFX", -1))

    terrain_rgb = palette(normalize(terrain), TERRAIN)

    burned = np.isfinite(level_set) & (level_set <= 0)
    burned[:3, :] = burned[-3:, :] = False
    burned[:, :3] = burned[:, -3:] = False
    tign_norm = np.clip(tign / 300.0, 0, 1)
    arrival_rgb = terrain_rgb.astype(np.float32) * 0.42
    arrival_rgb[burned] = palette(tign_norm, TIME)[burned]
    arrival_rgb[boundary(burned)] = (255, 255, 255)
    arrival_rgb = np.uint8(arrival_rgb)

    ros_good = np.isfinite(ros) & (ros >= 0) & (ros < 20)
    ros_high = float(np.nanpercentile(ros[ros_good], 99)) if np.any(ros_good) else 1.0
    ros_rgb = palette(normalize(ros, 0, max(ros_high, 0.1)), ROS)
    ros_rgb[~ros_good] = (230, 232, 234)

    hfx_good = np.isfinite(hfx) & (hfx > 0) & (hfx < 1e12)
    log_hfx = np.log10(np.maximum(hfx, 1.0))
    hfx_high = float(np.nanpercentile(log_hfx[hfx_good], 99)) if np.any(hfx_good) else 1.0
    hfx_rgb = palette(normalize(log_hfx, 0, max(hfx_high, 1.0)), FIRE)
    hfx_rgb[~hfx_good] = (238, 239, 240)

    canvas = Image.new("RGB", (1320, 1270), (247, 248, 249))
    draw = ImageDraw.Draw(canvas)
    draw.text((55, 30), "WRF-SFIRE baseline: idealized hill fire", fill=(17, 37, 58), font=font(35, bold=True))
    draw.text((55, 78), "Five-minute coupled atmosphere-fire simulation • ifire=1 • 6 m fire mesh", fill=(68, 79, 89), font=font(20))

    panel(canvas, grid_image(terrain_rgb), 55, 125, "Terrain", "Fire-grid surface elevation", TERRAIN, "low", "high")
    panel(canvas, grid_image(arrival_rgb), 690, 125, "Fire arrival", "Color = ignition time; white = final perimeter", TIME, "0 s", "300 s")
    panel(canvas, grid_image(ros_rgb), 55, 680, "Rate of spread", "Final ROS field", ROS, "0", f"{ros_high:.2f} m/s")
    panel(canvas, grid_image(hfx_rgb), 690, 680, "Fire heat flux", "Final FGRNHFX field; logarithmic color", FIRE, "0", f"10^{hfx_high:.1f} W/m²")
    draw.text((55, 1245), "Source: wrfout_d01_0001-01-01_00:00:00 • commit 9801186f3ef8", fill=(90, 98, 106), font=font(15))

    target = OUTPUT / "wrf-sfire-overview.png"
    canvas.save(target, optimize=True)
    return target


def create_animation(dataset: NetCDF) -> Path:
    crop = lambda values: values[5:-5, 5:-5]
    terrain = crop(dataset.read_float("ZSF", 0))
    terrain_rgb = palette(normalize(terrain), TERRAIN).astype(np.float32)
    frames = []
    # Every ten seconds, including initial and final state.
    for index in range(0, 61, 2):
        seconds = index * 5
        level_set = crop(dataset.read_float("LFN", index))
        fire_heat = crop(dataset.read_float("FGRNHFX", index))
        burned = np.isfinite(level_set) & (level_set <= 0)
        active = np.isfinite(fire_heat) & (fire_heat > 1000.0)
        burned[:3, :] = burned[-3:, :] = False
        burned[:, :3] = burned[:, -3:] = False
        active[:3, :] = active[-3:, :] = False
        active[:, :3] = active[:, -3:] = False
        rgb = terrain_rgb.copy()
        rgb[burned] = 0.38 * rgb[burned] + 0.62 * np.array((225, 93, 35))
        rgb[boundary(burned)] = (255, 241, 177)
        rgb[active] = (255, 50, 18)
        map_image = grid_image(np.uint8(np.clip(rgb, 0, 255)), 560)
        frame = Image.new("RGB", (700, 670), (247, 248, 249))
        draw = ImageDraw.Draw(frame)
        draw.text((38, 25), "WRF-SFIRE fire spread", fill=(17, 37, 58), font=font(31, bold=True))
        draw.text((38, 70), f"Simulation time: {seconds // 60:02d}:{seconds % 60:02d}", fill=(65, 76, 86), font=font(21))
        frame.paste(map_image, (38, 108))
        draw.rectangle((38, 108, 598, 668), outline=(100, 108, 116), width=2)
        draw.rectangle((615, 140, 635, 160), fill=(225, 93, 35))
        draw.text((642, 138), "burned", fill=(40, 45, 50), font=font(15))
        draw.rectangle((615, 180, 635, 200), fill=(255, 50, 18))
        draw.text((642, 178), "active", fill=(40, 45, 50), font=font(15))
        frames.append(frame)

    target = OUTPUT / "wrf-sfire-fire-spread.gif"
    frames[0].save(target, save_all=True, append_images=frames[1:], duration=180, loop=0, optimize=True)
    return target


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f"Missing input: {INPUT}")
    dataset = NetCDF(INPUT)
    try:
        overview = create_overview(dataset)
        animation = create_animation(dataset)
    finally:
        dataset.close()
    print(overview)
    print(animation)


if __name__ == "__main__":
    main()
