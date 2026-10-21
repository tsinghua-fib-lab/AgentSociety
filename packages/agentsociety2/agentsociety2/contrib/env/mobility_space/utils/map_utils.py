import itertools
import math
from typing import Literal

import numpy as np


def get_angle(x, y):
    return math.atan2(y, x) * 180 / math.pi


def point_on_line_given_distance(start_node, end_node, distance):
    """
    Given two points (start_point and end_point) defining a line, and a distance s to travel along the line,
    return the coordinates of the point reached after traveling s units along the line, starting from start_point.

    - **Args**:
        start_point (tuple): tuple of (x, y) representing the starting point on the line.
        end_point (tuple): tuple of (x, y) representing the ending point on the line.
        distance (float): Distance to travel along the line, starting from start_point.

    - **Returns**:
        tuple: tuple of (x, y) representing the new point reached after traveling s units along the line.
    """

    x1, y1 = start_node["x"], start_node["y"]
    x2, y2 = end_node["x"], end_node["y"]

    # Calculate the slope m and the y-intercept b of the line
    if x1 == x2:
        # Vertical line, distance is only along the y-axis
        return (x1, y1 + distance if distance >= 0 else y1 - abs(distance))
    else:
        # Calculate the direction vector (dx, dy) along the line
        length = math.hypot(x2 - x1, y2 - y1)
        dx = (x2 - x1) / length
        dy = (y2 - y1) / length

        # Scale the direction vector by the given distance
        scaled_dx = dx * distance
        scaled_dy = dy * distance

        # Calculate the new point's coordinates
        x = x1 + scaled_dx
        y = y1 + scaled_dy

        return [x, y]


def get_key_index_in_lane(
    nodes: list[dict[str, float]],
    distance: float,
    direction: Literal["front", "back"],
) -> int:
    if direction == "front":
        _nodes = [n for n in nodes]
        _index_offset, _index_factor = 0, 1
    elif direction == "back":
        _nodes = [n for n in nodes[::-1]]
        _index_offset, _index_factor = len(_nodes) - 1, -1
    else:
        raise ValueError(f"Invalid direction type {direction}!")
    _lane_points: list[tuple[float, float, float]] = [
        (n["x"], n["y"], n.get("z", 0)) for n in _nodes
    ]
    _line_lengths: list[float] = [0.0 for _ in range(len(_nodes))]
    _s = 0.0
    for i, (cur_p, next_p) in enumerate(itertools.pairwise(_lane_points)):
        _s += math.hypot(next_p[0] - cur_p[0], next_p[1] - cur_p[1])
        _line_lengths[i + 1] = _s
    s = np.clip(distance, _line_lengths[0], _line_lengths[-1])
    _key_index = 0
    for (
        prev_s,
        cur_s,
    ) in itertools.pairwise(_line_lengths):
        if prev_s <= s < cur_s:
            break
        _key_index += 1
    return _index_offset + _index_factor * _key_index


def get_xy_in_lane(
    nodes: list[dict[str, float]],
    distance: float,
    direction: Literal["front", "back"],
) -> tuple[float, float]:
    if direction == "front":
        _nodes = [n for n in nodes]
    elif direction == "back":
        _nodes = [n for n in nodes[::-1]]
    else:
        raise ValueError(f"Invalid direction type {direction}!")
    _lane_points: list[tuple[float, float, float]] = [
        (n["x"], n["y"], n.get("z", 0)) for n in _nodes
    ]
    _line_lengths: list[float] = [0.0 for _ in range(len(_nodes))]
    _s = 0.0
    for i, (cur_p, next_p) in enumerate(itertools.pairwise(_lane_points)):
        _s += math.hypot(next_p[0] - cur_p[0], next_p[1] - cur_p[1])
        _line_lengths[i + 1] = _s
    s = np.clip(distance, _line_lengths[0], _line_lengths[-1])
    for prev_s, prev_p, cur_s, cur_p in zip(
        _line_lengths[:-1],
        _lane_points[:-1],
        _line_lengths[1:],
        _lane_points[1:],
        strict=False,
    ):
        if prev_s <= s < cur_s:
            _delta_x, _delta_y, _delta_z = [
                cur_p[_idx] - prev_p[_idx] for _idx in [0, 1, 2]
            ]
            _blend_x, _blend_y, _blend_z = [prev_p[_idx] for _idx in [0, 1, 2]]
            _ratio = (s - prev_s) / (cur_s - prev_s)
            return (
                _blend_x + _ratio * _delta_x,
                _blend_y + _ratio * _delta_y,
                _blend_z + _ratio * _delta_z,
            )[:2]
    return _lane_points[-1][:2]


def get_direction_by_s(
    nodes: list[dict[str, float]],
    distance: float,
    direction: Literal["front", "back"],
) -> float:
    if direction == "front":
        _nodes = [n for n in nodes]
    elif direction == "back":
        _nodes = [n for n in nodes[::-1]]
    else:
        raise ValueError(f"Invalid direction type {direction}!")
    _lane_points: list[tuple[float, float, float]] = [
        (n["x"], n["y"], n.get("z", 0)) for n in _nodes
    ]
    _line_lengths: list[float] = [0.0 for _ in range(len(_nodes))]
    _line_directions: list[tuple[float, float]] = []
    _s = 0.0
    for i, (cur_p, next_p) in enumerate(itertools.pairwise(_lane_points)):
        _s += math.hypot(next_p[0] - cur_p[0], next_p[1] - cur_p[1])
        _line_lengths[i + 1] = _s
    for _i, (cur_p, next_p) in enumerate(itertools.pairwise(_lane_points)):
        _direction = math.atan2(next_p[1] - cur_p[1], next_p[0] - cur_p[0])
        _pitch = math.atan2(
            next_p[2] - cur_p[2],
            math.hypot(next_p[0] - cur_p[0], next_p[1] - cur_p[1]),
        )
        _line_directions.append((_direction / math.pi * 180, _pitch / math.pi * 180))
    s = np.clip(distance, _line_lengths[0], _line_lengths[-1])
    for prev_s, cur_s, direcs in zip(
        _line_lengths[:-1], _line_lengths[1:], _line_directions, strict=False
    ):
        if prev_s <= s < cur_s:
            return direcs[0]
    return _line_directions[-1][0]
