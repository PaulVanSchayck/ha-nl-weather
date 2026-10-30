"""Wind observation parsing, grid interpolation, and particle simulation for NL Weather."""

from __future__ import annotations

import io
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageDraw

from .helpers import Coordinate, epsg4325_to_epsg3857

COMPASS_DIRECTIONS: Sequence[str] = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def degrees_to_compass(deg: float) -> str:
    """Convert meteorological wind direction in degrees to compass direction."""
    idx = round((deg % 360) / 22.5) % 16
    return COMPASS_DIRECTIONS[idx]


def speed_to_bft(speed_ms: float) -> int:
    """Convert wind speed in m/s to Beaufort scale."""
    if speed_ms < 0.3:
        return 0
    if speed_ms < 1.6:
        return 1
    if speed_ms < 3.4:
        return 2
    if speed_ms < 5.5:
        return 3
    if speed_ms < 8.0:
        return 4
    if speed_ms < 10.8:
        return 5
    if speed_ms < 13.9:
        return 6
    if speed_ms < 17.2:
        return 7
    if speed_ms < 20.8:
        return 8
    if speed_ms < 24.5:
        return 9
    if speed_ms < 28.5:
        return 10
    if speed_ms < 32.7:
        return 11
    return 12


def speed_to_color(speed_ms: float, alpha: int) -> tuple[int, int, int, int]:
    """Map wind speed in m/s to particle trail color with given alpha."""
    if speed_ms < 3.0:
        # Gentle breeze / calm: electric cyan
        return (120, 225, 255, alpha)
    if speed_ms < 6.0:
        # Moderate: teal / mint
        return (90, 240, 200, alpha)
    if speed_ms < 10.0:
        # Fresh: vibrant green / lime
        return (150, 255, 90, alpha)
    if speed_ms < 15.0:
        # Strong: bright yellow
        return (255, 220, 60, alpha)
    # Gale / storm: vibrant orange / red
    return (255, 90, 60, alpha)


# Sampled color control points for KNMI WMS windspeed_0_10 (0..10 m/s)
WMS_WINDSPEED_COLOR_RAMP: Sequence[tuple[int, int, int, float]] = (
    (247, 247, 247, 10.0),
    (141, 8, 111, 9.37),
    (144, 29, 99, 8.92),
    (146, 45, 85, 8.47),
    (149, 58, 76, 8.02),
    (150, 69, 66, 7.57),
    (152, 85, 56, 7.12),
    (153, 97, 48, 6.67),
    (155, 113, 39, 6.22),
    (157, 129, 30, 5.76),
    (156, 144, 28, 5.31),
    (153, 161, 35, 4.86),
    (146, 177, 53, 4.41),
    (132, 193, 83, 3.96),
    (121, 201, 107, 3.51),
    (108, 212, 140, 3.06),
    (97, 221, 171, 2.61),
    (97, 229, 199, 2.16),
    (114, 236, 225, 1.70),
    (149, 241, 243, 1.25),
    (178, 242, 253, 0.80),
    (210, 248, 254, 0.30),
)


def decode_wms_wind_speed_color(
    r: int, g: int, b: int, max_speed: float = 10.0
) -> float:
    """Decode an RGB pixel from KNMI WMS windspeed heatmap to speed in m/s."""
    best_dist = 999999
    best_val = 0.0
    for cr, cg, cb, val in WMS_WINDSPEED_COLOR_RAMP:
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_val = val
    if max_speed != 10.0:
        return best_val * (max_speed / 10.0)
    return best_val


def decode_app_wind_speed_color(
    r: int, g: int, b: int, legend_steps: Sequence[dict]
) -> float:
    """Decode an RGB pixel using KNMI App API dynamic legend steps to m/s."""
    best_dist = 999999
    best_spd = 0.0
    for step in legend_steps:
        color_hex = step.get("color", "").lstrip("#")
        if len(color_hex) != 6:
            continue
        cr = int(color_hex[0:2], 16)
        cg = int(color_hex[2:4], 16)
        cb = int(color_hex[4:6], 16)
        val = float(step.get("value", 0)) / 3.6  # convert km/h to m/s
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_spd = val
    return best_spd


@dataclass(slots=True)
class WindObservation:
    """Single meteorological station wind observation."""

    station_id: str
    lon: float
    lat: float
    x: float
    y: float
    speed: float  # m/s
    direction: float  # degrees (wind FROM)
    u: float  # eastward velocity (m/s)
    v: float  # northward velocity (m/s)


def parse_edr_wind_coverages(coverages: list[dict]) -> list[WindObservation]:
    """Parse EDR cube coverage response into WindObservation objects."""
    observations: list[WindObservation] = []

    for cov in coverages:
        domain = cov.get("domain", {})
        axes = domain.get("axes", {})
        x_vals = axes.get("x", {}).get("values", [])
        y_vals = axes.get("y", {}).get("values", [])
        if not x_vals or not y_vals:
            continue

        lon = float(x_vals[0])
        lat = float(y_vals[0])

        # Filter out Caribbean stations or invalid coordinates
        if not (2.0 <= lon <= 8.0 and 50.0 <= lat <= 56.0):
            continue

        ranges = cov.get("ranges", {})
        dd_vals = ranges.get("dd", {}).get("values", [])
        ff_vals = ranges.get("ff", {}).get("values", [])

        if not dd_vals or not ff_vals:
            continue

        # Get the latest non-null observation
        dd_latest = None
        ff_latest = None
        for d, f in zip(reversed(dd_vals), reversed(ff_vals), strict=False):
            if d is not None and f is not None:
                dd_latest = float(d)
                ff_latest = float(f)
                break

        if dd_latest is None or ff_latest is None:
            continue

        rad = math.radians(dd_latest)
        # Wind direction is meteorological (from which wind blows)
        # u is eastward component (dx/dt): -speed * sin(rad)
        # v is northward component (dy/dt): -speed * cos(rad)
        u = -ff_latest * math.sin(rad)
        v = -ff_latest * math.cos(rad)

        mx, my = epsg4325_to_epsg3857(Coordinate(lat=lat, lon=lon))
        station_id = cov.get("eumetnet:locationId", f"{lon:.2f}_{lat:.2f}")

        observations.append(
            WindObservation(
                station_id=station_id,
                lon=lon,
                lat=lat,
                x=mx,
                y=my,
                speed=ff_latest,
                direction=dd_latest,
                u=u,
                v=v,
            )
        )

    return observations


def create_app_target_wind_observation(
    station_id: str,
    lat: float,
    lon: float,
    wind_data: dict | None,
) -> WindObservation | None:
    """Create a WindObservation from KNMI App API wind data at target location."""
    if not wind_data or not isinstance(wind_data, dict):
        return None

    speed_kmh = wind_data.get("speed")
    direction = wind_data.get("degree")
    if speed_kmh is None or direction is None:
        return None

    try:
        speed_ms = float(speed_kmh) / 3.6
        direction_deg = float(direction)
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return None

    # Filter out invalid coordinates outside Netherlands region
    if not (2.0 <= lon_f <= 8.0 and 50.0 <= lat_f <= 56.0):
        return None

    rad = math.radians(direction_deg)
    # Wind direction is meteorological (from which wind blows)
    # u is eastward component (dx/dt): -speed * sin(rad)
    # v is northward component (dy/dt): -speed * cos(rad)
    u = -speed_ms * math.sin(rad)
    v = -speed_ms * math.cos(rad)

    mx, my = epsg4325_to_epsg3857(Coordinate(lat=lat_f, lon=lon_f))

    return WindObservation(
        station_id=station_id,
        lon=lon_f,
        lat=lat_f,
        x=mx,
        y=my,
        speed=speed_ms,
        direction=direction_deg,
        u=u,
        v=v,
    )


class WindVectorGrid:
    """2D spatial grid of wind vectors interpolated via Inverse Distance Weighting."""

    def __init__(
        self,
        observations: list[WindObservation],
        bbox: tuple[float, float, float, float],
        grid_w: int = 40,
        grid_h: int = 40,
    ) -> None:
        self.bbox = bbox
        self.grid_w = grid_w
        self.grid_h = grid_h
        self.observations = observations

        min_x, min_y, max_x, max_y = bbox
        self.min_x = min_x
        self.min_y = min_y
        self.max_x = max_x
        self.max_y = max_y

        self.u_grid: list[list[float]] = [[0.0] * grid_w for _ in range(grid_h)]
        self.v_grid: list[list[float]] = [[0.0] * grid_w for _ in range(grid_h)]

        self.mean_speed: float = 0.0
        self.mean_direction: float = 0.0

        self._interpolate()

    def _interpolate(self) -> None:
        if not self.observations:
            return

        total_spd = sum(obs.speed for obs in self.observations)
        self.mean_speed = total_spd / len(self.observations)

        mean_u = sum(obs.u for obs in self.observations) / len(self.observations)
        mean_v = sum(obs.v for obs in self.observations) / len(self.observations)
        # Reconstruct meteorological direction from mean u, v
        self.mean_direction = (math.degrees(math.atan2(-mean_u, -mean_v)) + 360) % 360

        dx_step = (self.max_x - self.min_x) / max(self.grid_w - 1, 1)
        # Note: in EPSG:3857, max_y is at the top (North), min_y at bottom (South)
        dy_step = (self.max_y - self.min_y) / max(self.grid_h - 1, 1)

        # IDW interpolation
        for row in range(self.grid_h):
            grid_y = self.max_y - row * dy_step
            for col in range(self.grid_w):
                grid_x = self.min_x + col * dx_step

                w_sum = 0.0
                u_sum = 0.0
                v_sum = 0.0

                for obs in self.observations:
                    dist_sq = (grid_x - obs.x) ** 2 + (grid_y - obs.y) ** 2 + 1000.0
                    w = 1.0 / dist_sq
                    w_sum += w
                    u_sum += w * obs.u
                    v_sum += w * obs.v

                if w_sum > 0:
                    self.u_grid[row][col] = u_sum / w_sum
                    self.v_grid[row][col] = v_sum / w_sum

    def apply_speed_raster(
        self,
        speed_img: Image.Image,
        max_speed: float = 10.0,
        legend_steps: Sequence[dict] | None = None,
    ) -> int:
        """Modulate vector speeds across the grid using a high-resolution WMS/App wind speed raster.

        Preserves the exact direction from the EDR station wind field.
        Cells where the raster is masked (transparent) retain their interpolated EDR speeds.
        Returns the number of modulated cells.
        """
        img = speed_img.convert("RGBA") if speed_img.mode != "RGBA" else speed_img
        img_w, img_h = img.size
        modulated = 0

        for row in range(self.grid_h):
            py = int((row / max(self.grid_h - 1, 1)) * (img_h - 1))
            for col in range(self.grid_w):
                px = int((col / max(self.grid_w - 1, 1)) * (img_w - 1))
                r, g, b, a = img.getpixel((px, py))
                if a < 30:
                    continue

                if legend_steps:
                    raster_spd = decode_app_wind_speed_color(r, g, b, legend_steps)
                else:
                    raster_spd = decode_wms_wind_speed_color(r, g, b, max_speed)

                u = self.u_grid[row][col]
                v = self.v_grid[row][col]
                cur_spd = math.hypot(u, v)
                if cur_spd > 1e-4:
                    self.u_grid[row][col] = (u / cur_spd) * raster_spd
                    self.v_grid[row][col] = (v / cur_spd) * raster_spd
                else:
                    self.u_grid[row][col] = raster_spd
                modulated += 1

        return modulated

    def get_velocity_at(
        self, px: float, py: float, width: int, height: int
    ) -> tuple[float, float]:
        """Lookup velocity at normalized screen coordinates."""
        col = min(max(int(px / width * (self.grid_w - 1)), 0), self.grid_w - 1)
        row = min(max(int(py / height * (self.grid_h - 1)), 0), self.grid_h - 1)
        # Return u (eastward, +x) and -v (northward, -y in screen coordinates)
        return self.u_grid[row][col], -self.v_grid[row][col]


class WindParticleEngine:
    """Seamless looping particle animation generator for wind maps."""

    def __init__(
        self,
        grid: WindVectorGrid,
        canvas_size: tuple[int, int] = (600, 600),
        n_particles: int = 750,
        n_frames: int = 30,
        frame_duration_ms: int = 70,
        vel_scale: float = 0.85,
        seed: int = 42,
    ) -> None:
        self.grid = grid
        self.width, self.height = canvas_size
        self.n_particles = n_particles
        self.n_frames = n_frames
        self.frame_duration_ms = frame_duration_ms
        self.vel_scale = vel_scale
        self.seed = seed

    def render_animation(
        self,
        base_map: Image.Image,
        timestamp: datetime | None = None,
        header_color: str = "rgb(230, 230, 230)",
    ) -> bytes:
        """Render seamless particle animation and return GIF bytes."""
        rng = random.Random(self.seed)

        # Scale base map to canvas size if necessary
        if base_map.size != (self.width, self.height):
            base_bg = base_map.resize(
                (self.width, self.height), Image.Resampling.LANCZOS
            ).convert("RGBA")
        else:
            base_bg = base_map.convert("RGBA")

        # Spawn particles with margin around screen so incoming particles are already visible
        margin = 40
        spawn_x = [
            rng.uniform(-margin, self.width + margin) for _ in range(self.n_particles)
        ]
        spawn_y = [
            rng.uniform(-margin, self.height + margin) for _ in range(self.n_particles)
        ]
        birth_frames = [
            rng.randint(0, self.n_frames - 1) for _ in range(self.n_particles)
        ]

        # Precompute particle paths: length n_frames + 1
        # paths[i][step] = (x, y)
        paths: list[list[tuple[float, float]]] = [
            [(spawn_x[i], spawn_y[i])] for i in range(self.n_particles)
        ]

        for step in range(self.n_frames):
            for i in range(self.n_particles):
                curr_x, curr_y = paths[i][step]
                u, v_screen = self.grid.get_velocity_at(
                    curr_x, curr_y, self.width, self.height
                )
                next_x = curr_x + u * self.vel_scale
                next_y = curr_y + v_screen * self.vel_scale
                paths[i].append((next_x, next_y))

        # Header time text (matching precipitation radar map style)
        header_text = timestamp.strftime("%a %H:%M") if timestamp else None

        frames: list[Image.Image] = []

        for f in range(self.n_frames):
            frame = base_bg.copy()
            overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            for i in range(self.n_particles):
                # Harmonic sine opacity ensures 0 at birth and 0 at death for seamless looping
                k = (f - birth_frames[i]) % self.n_frames
                alpha = int(220.0 * math.sin(k / self.n_frames * math.pi))
                if alpha <= 8:
                    continue

                x1, y1 = paths[i][k]
                x2, y2 = paths[i][k + 1]

                # Skip line segments that are completely outside the visible canvas
                if (x1 < 0 and x2 < 0) or (x1 > self.width and x2 > self.width):
                    continue
                if (y1 < 0 and y2 < 0) or (y1 > self.height and y2 > self.height):
                    continue

                dx = x2 - x1
                dy = y2 - y1
                seg_len = math.hypot(dx, dy)
                # Keep a subtle minimum streak length of 2.5px so slow particles remain sleek
                if 0 < seg_len < 2.5:
                    x2 = x1 + dx * (2.5 / seg_len)
                    y2 = y1 + dy * (2.5 / seg_len)

                spd = seg_len / self.vel_scale
                color = speed_to_color(spd, alpha)
                draw.line([(x1, y1), (x2, y2)], fill=color, width=2)

            comp = Image.alpha_composite(frame, overlay)

            # Draw time text on frame (identical to precipitation radar map style)
            if header_text:
                draw_comp = ImageDraw.Draw(comp)
                pos_x = round(28 * (self.width / 1024))
                pos_y = round(28 * (self.height / 1024))
                font_sz = max(round(45 * (self.width / 1024)), 20)
                draw_comp.text(
                    (pos_x, pos_y),
                    header_text,
                    fill=header_color,
                    font_size=font_sz,
                    stroke_width=0.8,
                )

            frames.append(comp.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))

        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=self.frame_duration_ms,
            loop=0,
            optimize=True,
        )
        return output.getvalue()
