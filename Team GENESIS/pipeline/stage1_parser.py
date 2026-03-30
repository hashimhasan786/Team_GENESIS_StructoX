"""
Stage 1 — Floor Plan Parser  (v3 — robust text-aware)
=======================================================
Detects and extracts:
  • Walls  (line segments, classified horizontal / vertical / diagonal)
  • Rooms  (enclosed regions via contour analysis)
  • Openings (doors & windows via gap detection)
  • Corners / junctions (T/L/X classification)

Key improvements over v2:
  - Multi-layered text removal: MSER + CC analysis + morphological filtering
  - Wall back-projection validation: candidate lines checked against actual
    pixel density on the cleaned binary image
  - Otsu auto-thresholding instead of hardcoded value
  - Thickness-based post-filtering rejects thin strokes (text remnants)
  - More robust ROI detection and fallback

Returns:
  parsed_data  — structured dict with all geometry
  annotated    — BGR annotated image (numpy array)
"""

import cv2
import numpy as np
import math
import json
from collections import defaultdict


# ─── helpers ───────────────────────────────────────────────────────────────

def _angle(x1, y1, x2, y2):
    return math.degrees(math.atan2(abs(y2 - y1), abs(x2 - x1)))


def _length(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def _snap(val, grid=5):
    return round(val / grid) * grid


def _snap_line(x1, y1, x2, y2, grid=5):
    return _snap(x1, grid), _snap(y1, grid), _snap(x2, grid), _snap(y2, grid)


def _midpoint(x1, y1, x2, y2):
    return (x1 + x2) / 2, (y1 + y2) / 2


def _point_to_line_distance(px, py, x1, y1, x2, y2):
    """Perpendicular distance from point (px,py) to line segment (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


# ─── ROI extraction ────────────────────────────────────────────────────────

def _find_floor_plan_roi(gray, img_bgr):
    """
    Detect the bounding rectangle of the actual floor plan,
    excluding title text, scale bars, and description text.
    """
    h, w = gray.shape

    # Use Otsu to find a good threshold automatically
    otsu_val, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Strong threshold to get only the darkest elements (walls are black)
    thresh_val = min(otsu_val, 100)
    _, strong_bin = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY_INV)

    # Dilate aggressively to connect wall segments into a continuous boundary
    kernel_big = np.ones((15, 15), np.uint8)
    dilated = cv2.dilate(strong_bin, kernel_big, iterations=3)
    dilated = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel_big, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    img_area = h * w
    best_roi = None
    best_area = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < img_area * 0.08:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        rect_area = bw * bh
        fill = area / rect_area if rect_area > 0 else 0
        if fill > 0.35 and rect_area > best_area:
            best_area = rect_area
            best_roi = (x, y, bw, bh)

    if best_roi is None:
        # Fallback: use the whole image with small margins
        margin_top = int(h * 0.02)
        margin_bottom = int(h * 0.98)
        margin_left = int(w * 0.02)
        margin_right = int(w * 0.98)
        best_roi = (margin_left, margin_top,
                    margin_right - margin_left,
                    margin_bottom - margin_top)

    return best_roi


# ─── Text removal (multi-layered) ──────────────────────────────────────────

def _detect_text_regions_mser(gray_roi):
    """
    Use MSER to detect text-like regions.  Returns a mask of text areas.
    """
    h, w = gray_roi.shape
    text_mask = np.zeros((h, w), dtype=np.uint8)

    try:
        mser = cv2.MSER_create()
        mser.setMinArea(30)
        mser.setMaxArea(int(h * w * 0.003))  # text chars are tiny vs image

        regions, _ = mser.detectRegions(gray_roi)

        for region in regions:
            hull = cv2.convexHull(region.reshape(-1, 1, 2))
            x, y, rw, rh = cv2.boundingRect(hull)
            area = cv2.contourArea(hull)
            rect_area = rw * rh
            if rect_area == 0:
                continue

            # Text characters: small, roughly square or slightly tall,
            # high solidity (fill ratio), limited size
            max_dim = max(rw, rh)
            min_dim = min(rw, rh) + 1
            aspect = max_dim / min_dim
            solidity = area / rect_area

            # Text heuristics
            is_text_sized = max_dim < min(h, w) * 0.06
            is_char_shaped = aspect < 4.0 and solidity > 0.2
            is_small_area = area < h * w * 0.002

            if is_text_sized and is_char_shaped and is_small_area:
                # Expand slightly to catch anti-aliased edges
                pad = 3
                x0 = max(0, x - pad)
                y0 = max(0, y - pad)
                x1 = min(w, x + rw + pad)
                y1 = min(h, y + rh + pad)
                text_mask[y0:y1, x0:x1] = 255
    except Exception:
        pass  # MSER can fail on some images; fall through to other methods

    # Dilate text mask to merge nearby characters into text blocks
    if np.any(text_mask):
        text_mask = cv2.dilate(text_mask, np.ones((5, 11), np.uint8), iterations=1)

    return text_mask


def _remove_text_from_binary(binary, gray_roi=None, wall_thickness_estimate=None):
    """
    Remove text from a binary image while preserving thick wall lines.

    Three-pronged approach:
      1. MSER-based text region detection (if gray available)
      2. Connected component filtering (aspect ratio + size)
      3. Morphological directional opening (keep only long H/V strokes)
    """
    h, w = binary.shape

    if wall_thickness_estimate is None:
        wall_thickness_estimate = max(3, int(min(h, w) * 0.008))

    # ── Layer 1: MSER text mask ──
    text_mask = np.zeros_like(binary)
    if gray_roi is not None:
        text_mask = _detect_text_regions_mser(gray_roi)

    # Subtract detected text regions from binary
    binary_no_text = binary.copy()
    if np.any(text_mask):
        binary_no_text = cv2.bitwise_and(binary_no_text, cv2.bitwise_not(text_mask))

    # ── Layer 2: Connected component filtering ──
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary_no_text, connectivity=8
    )

    min_wall_length = max(int(min(h, w) * 0.04), 20)
    min_wall_area = min_wall_length * wall_thickness_estimate
    cleaned = np.zeros_like(binary)

    for i in range(1, num_labels):
        comp_x = stats[i, cv2.CC_STAT_LEFT]
        comp_y = stats[i, cv2.CC_STAT_TOP]
        comp_w = stats[i, cv2.CC_STAT_WIDTH]
        comp_h = stats[i, cv2.CC_STAT_HEIGHT]
        comp_area = stats[i, cv2.CC_STAT_AREA]

        max_dim = max(comp_w, comp_h)
        min_dim = min(comp_w, comp_h) + 1
        aspect = max_dim / min_dim

        # Calculate how densely the component fills its bounding box
        bbox_area = comp_w * comp_h
        fill_ratio = comp_area / bbox_area if bbox_area > 0 else 0

        # ── Reject conditions (text-like) ──
        # Text characters: small, compact, high fill ratio, not elongated
        is_tiny = max_dim < min(h, w) * 0.03
        is_text_char = (aspect < 3.0 and max_dim < min(h, w) * 0.05
                        and fill_ratio > 0.15 and comp_area < min_wall_area * 0.5)
        is_small_blob = comp_area < wall_thickness_estimate * 8

        if is_tiny or is_text_char or is_small_blob:
            continue  # reject as text/noise

        # ── Keep conditions (wall-like) ──
        is_elongated = aspect > 3.5 and max_dim > min_wall_length
        is_large = comp_area > min_wall_area
        is_very_elongated = aspect > 6.0 and max_dim > min(h, w) * 0.025
        # Thick connected structure (room boundary / wall cluster)
        is_structural = (comp_area > min_wall_area * 3
                         and max_dim > min(h, w) * 0.08)

        if is_elongated or is_large or is_very_elongated or is_structural:
            cleaned[labels == i] = 255

    # ── Layer 3: Morphological directional opening ──
    # Extract only long horizontal lines
    h_kernel_len = max(20, int(w * 0.04))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_len, 1))
    h_lines = cv2.morphologyEx(binary_no_text, cv2.MORPH_OPEN, h_kernel)

    # Extract only long vertical lines
    v_kernel_len = max(20, int(h * 0.04))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
    v_lines = cv2.morphologyEx(binary_no_text, cv2.MORPH_OPEN, v_kernel)

    morph_walls = cv2.bitwise_or(h_lines, v_lines)

    # Dilate morphological result slightly to reconnect wall segments
    morph_walls = cv2.dilate(morph_walls, np.ones((3, 3), np.uint8), iterations=1)

    # Final: union of CC-filtered and morphological
    result = cv2.bitwise_or(cleaned, morph_walls)

    # Light cleanup
    result = cv2.morphologyEx(result, cv2.MORPH_CLOSE,
                               np.ones((3, 3), np.uint8), iterations=1)

    return result


# ─── Wall back-projection validation ──────────────────────────────────────

def _validate_wall_on_binary(binary_clean, x1, y1, x2, y2, thickness=5):
    """
    Check that a candidate wall line actually corresponds to drawn pixels
    in the cleaned binary image.  Returns the fraction of sampled points
    that overlap with white pixels (0.0 – 1.0).
    """
    h, w = binary_clean.shape
    length = _length(x1, y1, x2, y2)
    if length < 2:
        return 0.0

    n_samples = max(10, int(length / 3))
    hits = 0

    for i in range(n_samples):
        t = i / (n_samples - 1)
        px = int(x1 + t * (x2 - x1))
        py = int(y1 + t * (y2 - y1))

        # Check a small region around the point (wall has thickness)
        found = False
        for dy in range(-thickness, thickness + 1):
            for dx in range(-thickness, thickness + 1):
                nx, ny = px + dx, py + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if binary_clean[ny, nx] > 0:
                        found = True
                        break
            if found:
                break
        if found:
            hits += 1

    return hits / n_samples


# ─── Collinear wall merging ───────────────────────────────────────────────

def _merge_collinear_walls(walls, angle_tol=8.0, dist_tol=15, gap_tol=25):
    """
    Merge wall segments that are roughly collinear, close together,
    and overlapping/nearly overlapping in their primary axis.
    """
    if not walls:
        return walls

    merged = list(walls)
    changed = True

    while changed:
        changed = False
        new_merged = []
        used = set()

        for i in range(len(merged)):
            if i in used:
                continue
            w1 = merged[i]
            best_j = None
            best_new = None

            for j in range(i + 1, len(merged)):
                if j in used:
                    continue
                w2 = merged[j]

                if w1["orientation"] != w2["orientation"]:
                    continue

                angle_diff = abs(w1["angle_deg"] - w2["angle_deg"])
                if angle_diff > angle_tol:
                    continue

                if w1["orientation"] == "horizontal":
                    y_dist = abs((w1["y1"] + w1["y2"]) / 2 - (w2["y1"] + w2["y2"]) / 2)
                    if y_dist > dist_tol:
                        continue
                    min1, max1 = min(w1["x1"], w1["x2"]), max(w1["x1"], w1["x2"])
                    min2, max2 = min(w2["x1"], w2["x2"]), max(w2["x1"], w2["x2"])
                    gap = max(min1, min2) - min(max1, max2)
                    if gap > gap_tol:
                        continue
                    new_x1 = min(min1, min2)
                    new_x2 = max(max1, max2)
                    avg_y = int((w1["y1"] + w1["y2"] + w2["y1"] + w2["y2"]) / 4)
                    best_j = j
                    best_new = {
                        "x1": new_x1, "y1": avg_y,
                        "x2": new_x2, "y2": avg_y,
                    }

                elif w1["orientation"] == "vertical":
                    x_dist = abs((w1["x1"] + w1["x2"]) / 2 - (w2["x1"] + w2["x2"]) / 2)
                    if x_dist > dist_tol:
                        continue
                    min1, max1 = min(w1["y1"], w1["y2"]), max(w1["y1"], w1["y2"])
                    min2, max2 = min(w2["y1"], w2["y2"]), max(w2["y1"], w2["y2"])
                    gap = max(min1, min2) - min(max1, max2)
                    if gap > gap_tol:
                        continue
                    new_y1 = min(min1, min2)
                    new_y2 = max(max1, max2)
                    avg_x = int((w1["x1"] + w1["x2"] + w2["x1"] + w2["x2"]) / 4)
                    best_j = j
                    best_new = {
                        "x1": avg_x, "y1": new_y1,
                        "x2": avg_x, "y2": new_y2,
                    }

            if best_j is not None:
                llen = _length(best_new["x1"], best_new["y1"],
                               best_new["x2"], best_new["y2"])
                mx, my = _midpoint(best_new["x1"], best_new["y1"],
                                   best_new["x2"], best_new["y2"])
                ang = _angle(best_new["x1"], best_new["y1"],
                             best_new["x2"], best_new["y2"])
                merged_wall = {
                    "id": w1["id"],
                    "x1": int(best_new["x1"]), "y1": int(best_new["y1"]),
                    "x2": int(best_new["x2"]), "y2": int(best_new["y2"]),
                    "length_px": round(llen, 1),
                    "angle_deg": round(ang, 1),
                    "orientation": w1["orientation"],
                    "midpoint": [round(mx, 1), round(my, 1)],
                }
                new_merged.append(merged_wall)
                used.add(i)
                used.add(best_j)
                changed = True
            else:
                new_merged.append(w1)
                used.add(i)

        merged = new_merged

    return merged


def _measure_wall_thickness(binary_roi, walls):
    """
    For each wall, measure its thickness by sampling perpendicular cross-sections.
    Returns the median thickness estimate.
    """
    h, w = binary_roi.shape
    thicknesses = []

    for wall in walls:
        x1, y1, x2, y2 = wall["x1"], wall["y1"], wall["x2"], wall["y2"]
        mx, my = int((x1 + x2) / 2), int((y1 + y2) / 2)

        if wall["orientation"] == "horizontal":
            col = min(max(mx, 0), w - 1)
            column = binary_roi[:, col]
            runs = _find_runs(column, my)
            if runs:
                thicknesses.append(runs)
        elif wall["orientation"] == "vertical":
            row = min(max(my, 0), h - 1)
            row_data = binary_roi[row, :]
            runs = _find_runs(row_data, mx)
            if runs:
                thicknesses.append(runs)

    if thicknesses:
        return int(np.median(thicknesses))
    return max(3, int(min(h, w) * 0.008))


def _find_runs(line_data, target_pos):
    """Find the length of the white run containing target_pos."""
    n = len(line_data)
    if target_pos < 0 or target_pos >= n:
        return 0
    if line_data[target_pos] == 0:
        for offset in range(1, 15):
            if target_pos + offset < n and line_data[target_pos + offset] > 0:
                target_pos = target_pos + offset
                break
            if target_pos - offset >= 0 and line_data[target_pos - offset] > 0:
                target_pos = target_pos - offset
                break
        else:
            return 0

    start = target_pos
    while start > 0 and line_data[start - 1] > 0:
        start -= 1
    end = target_pos
    while end < n - 1 and line_data[end + 1] > 0:
        end += 1
    return end - start + 1


# ─── Duplicate wall removal ───────────────────────────────────────────────

def _remove_duplicate_walls(walls, dist_threshold=10):
    """
    Remove near-duplicate wall segments (same orientation, very close
    endpoints).  Keeps the longer of each duplicate pair.
    """
    if not walls:
        return walls

    # Sort by length descending so we prefer keeping longer walls
    walls_sorted = sorted(walls, key=lambda w: w["length_px"], reverse=True)
    kept = []
    removed = set()

    for i, w1 in enumerate(walls_sorted):
        if i in removed:
            continue
        kept.append(w1)
        for j in range(i + 1, len(walls_sorted)):
            if j in removed:
                continue
            w2 = walls_sorted[j]
            if w1["orientation"] != w2["orientation"]:
                continue

            # Check if endpoints are very close
            d_start = _length(w1["x1"], w1["y1"], w2["x1"], w2["y1"])
            d_end = _length(w1["x2"], w1["y2"], w2["x2"], w2["y2"])
            d_cross1 = _length(w1["x1"], w1["y1"], w2["x2"], w2["y2"])
            d_cross2 = _length(w1["x2"], w1["y2"], w2["x1"], w2["y1"])

            if ((d_start < dist_threshold and d_end < dist_threshold) or
                    (d_cross1 < dist_threshold and d_cross2 < dist_threshold)):
                removed.add(j)

            # Also check if w2 is completely contained within w1
            if w1["orientation"] == "horizontal":
                y_close = abs((w1["y1"] + w1["y2"]) / 2 - (w2["y1"] + w2["y2"]) / 2) < dist_threshold
                if y_close:
                    min1, max1 = min(w1["x1"], w1["x2"]), max(w1["x1"], w1["x2"])
                    min2, max2 = min(w2["x1"], w2["x2"]), max(w2["x1"], w2["x2"])
                    if min2 >= min1 - dist_threshold and max2 <= max1 + dist_threshold:
                        removed.add(j)
            elif w1["orientation"] == "vertical":
                x_close = abs((w1["x1"] + w1["x2"]) / 2 - (w2["x1"] + w2["x2"]) / 2) < dist_threshold
                if x_close:
                    min1, max1 = min(w1["y1"], w1["y2"]), max(w1["y1"], w1["y2"])
                    min2, max2 = min(w2["y1"], w2["y2"]), max(w2["y1"], w2["y2"])
                    if min2 >= min1 - dist_threshold and max2 <= max1 + dist_threshold:
                        removed.add(j)

    return kept


# ─── main function ──────────────────────────────────────────────────────────

def parse_floor_plan(image_path: str) -> tuple:
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise ValueError(f"Cannot read image: {image_path}")

    orig_h, orig_w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # ── Step 1: Find the floor plan ROI ─────────────────────────────────────
    roi_x, roi_y, roi_w, roi_h = _find_floor_plan_roi(gray, img_bgr)

    pad = 10
    roi_x = max(0, roi_x - pad)
    roi_y = max(0, roi_y - pad)
    roi_w = min(orig_w - roi_x, roi_w + 2 * pad)
    roi_h = min(orig_h - roi_y, roi_h + 2 * pad)

    gray_roi = gray[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
    img_roi = img_bgr[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]

    annotated = img_bgr.copy()

    # Draw ROI boundary (debugging)
    cv2.rectangle(annotated, (roi_x, roi_y),
                  (roi_x + roi_w, roi_y + roi_h), (0, 180, 0), 2)

    # ── Step 2: Binary thresholding ─────────────────────────────────────────
    # Use Otsu for automatic threshold selection
    otsu_val, binary_otsu = cv2.threshold(
        gray_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    # Also use a tighter threshold to capture only the darkest pixels (walls)
    # Walls in floor plans are typically very dark (< 100 intensity)
    tight_thresh = min(int(otsu_val * 0.75), 100)
    _, binary_tight = cv2.threshold(gray_roi, tight_thresh, 255, cv2.THRESH_BINARY_INV)

    # Primary binary: use the tighter threshold for wall detection
    # This naturally excludes lighter text, dimensions, hatching
    binary = binary_tight.copy()

    # ── Step 3: Remove text from binary (multi-layered) ─────────────────────
    binary_clean = _remove_text_from_binary(binary, gray_roi=gray_roi)

    # ── Step 4: Wall detection — two-pass approach ──────────────────────────
    #
    # Pass A: Morphological line extraction (very reliable, catches obvious walls)
    # Pass B: HoughLinesP on cleaned edges (catches remaining walls)
    # Both passes validate lines against the cleaned binary (back-projection)

    # -- Pass A: Morphological --
    morph_min_len = max(25, int(min(roi_w, roi_h) * 0.06))

    h_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_min_len, 1))
    morph_h = cv2.morphologyEx(binary_clean, cv2.MORPH_OPEN, h_kern)

    v_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, morph_min_len))
    morph_v = cv2.morphologyEx(binary_clean, cv2.MORPH_OPEN, v_kern)

    morph_combined = cv2.bitwise_or(morph_h, morph_v)
    # Slight dilation to connect broken segments
    morph_combined = cv2.dilate(morph_combined, np.ones((3, 3), np.uint8), iterations=1)

    # Run HoughLinesP on morphological result
    edges_morph = cv2.Canny(morph_combined, 50, 150, apertureSize=3)
    morph_lines = cv2.HoughLinesP(
        edges_morph,
        rho=1, theta=np.pi / 180,
        threshold=30,
        minLineLength=max(20, int(min(roi_w, roi_h) * 0.04)),
        maxLineGap=max(10, int(min(roi_w, roi_h) * 0.02))
    )

    # -- Pass B: HoughLinesP on cleaned Canny edges --
    edges_clean = cv2.Canny(binary_clean, 50, 150, apertureSize=3, L2gradient=True)

    min_line_len = max(30, int(min(roi_w, roi_h) * 0.05))
    max_line_gap = max(10, int(min(roi_w, roi_h) * 0.015))

    hough_lines = cv2.HoughLinesP(
        edges_clean,
        rho=1, theta=np.pi / 180,
        threshold=50,
        minLineLength=min_line_len,
        maxLineGap=max_line_gap
    )

    # Combine both sets of raw lines
    all_raw_lines = []
    if morph_lines is not None:
        all_raw_lines.extend(morph_lines)
    if hough_lines is not None:
        all_raw_lines.extend(hough_lines)

    # ── Step 5: Filter & validate candidate walls ───────────────────────────
    walls = []
    h_walls, v_walls, d_walls = [], [], []

    SNAP = 5
    # Minimum back-projection overlap ratio to accept a wall
    MIN_OVERLAP = 0.35

    for ln in all_raw_lines:
        x1, y1, x2, y2 = ln[0]
        x1, y1, x2, y2 = _snap_line(x1, y1, x2, y2, SNAP)
        ang = _angle(x1, y1, x2, y2)
        llen = _length(x1, y1, x2, y2)

        # Reject very short lines
        if llen < min_line_len * 0.8:
            continue

        # Reject diagonals unless very long
        if 15 <= ang <= 75 and llen < min(roi_w, roi_h) * 0.15:
            continue

        # ── Back-projection validation ──
        # Check that this line actually corresponds to drawn wall pixels
        overlap = _validate_wall_on_binary(
            binary_clean, x1, y1, x2, y2,
            thickness=max(3, int(min(roi_h, roi_w) * 0.008))
        )
        if overlap < MIN_OVERLAP:
            continue  # phantom line — not backed by actual pixels

        # Classify orientation
        if ang < 15:
            orient = "horizontal"
        elif ang > 75:
            orient = "vertical"
        else:
            orient = "diagonal"

        mx, my = _midpoint(x1, y1, x2, y2)

        wall = {
            "id": len(walls),
            "x1": int(x1) + roi_x, "y1": int(y1) + roi_y,
            "x2": int(x2) + roi_x, "y2": int(y2) + roi_y,
            "length_px": round(llen, 1),
            "angle_deg": round(ang, 1),
            "orientation": orient,
            "midpoint": [round(mx + roi_x, 1), round(my + roi_y, 1)],
            "back_proj_score": round(overlap, 2),
        }
        walls.append(wall)

        if orient == "horizontal":
            h_walls.append(wall)
        elif orient == "vertical":
            v_walls.append(wall)
        else:
            d_walls.append(wall)

    # ── Step 6: Merge collinear overlapping segments ────────────────────────
    walls = _merge_collinear_walls(walls)

    # ── Step 7: Remove near-duplicate walls ─────────────────────────────────
    walls = _remove_duplicate_walls(walls, dist_threshold=12)

    # Recategorize after merge/dedup
    h_walls = [w for w in walls if w["orientation"] == "horizontal"]
    v_walls = [w for w in walls if w["orientation"] == "vertical"]
    d_walls = [w for w in walls if w["orientation"] == "diagonal"]

    # Re-index wall IDs
    for idx, w in enumerate(walls):
        w["id"] = idx

    # ── Step 8: Thickness-based post-filtering ──────────────────────────────
    wall_thickness = _measure_wall_thickness(binary_clean, [
        {"x1": w["x1"] - roi_x, "y1": w["y1"] - roi_y,
         "x2": w["x2"] - roi_x, "y2": w["y2"] - roi_y,
         "orientation": w["orientation"]}
        for w in walls[:30]
    ])

    # Filter walls that are too thin (likely text remnants that survived)
    min_thickness = max(2, int(wall_thickness * 0.4))
    filtered_walls = []
    for w in walls:
        # Re-measure this specific wall's thickness
        local_w = {"x1": w["x1"] - roi_x, "y1": w["y1"] - roi_y,
                   "x2": w["x2"] - roi_x, "y2": w["y2"] - roi_y,
                   "orientation": w["orientation"]}
        local_thickness = _measure_wall_thickness(binary_clean, [local_w])
        if local_thickness >= min_thickness:
            filtered_walls.append(w)

    walls = filtered_walls

    # Re-categorize and re-index after filtering
    h_walls = [w for w in walls if w["orientation"] == "horizontal"]
    v_walls = [w for w in walls if w["orientation"] == "vertical"]
    d_walls = [w for w in walls if w["orientation"] == "diagonal"]
    for idx, w in enumerate(walls):
        w["id"] = idx

    # ── Draw walls on annotated image ───────────────────────────────────────
    for w in walls:
        x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]
        if w["orientation"] == "horizontal":
            cv2.line(annotated, (x1, y1), (x2, y2), (0, 200, 255), 2)
        elif w["orientation"] == "vertical":
            cv2.line(annotated, (x1, y1), (x2, y2), (255, 120, 30), 2)
        else:
            cv2.line(annotated, (x1, y1), (x2, y2), (0, 210, 120), 2)

    # ── Room Detection ──────────────────────────────────────────────────────
    wall_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
    for w in walls:
        pt1 = (w["x1"] - roi_x, w["y1"] - roi_y)
        pt2 = (w["x2"] - roi_x, w["y2"] - roi_y)
        cv2.line(wall_mask, pt1, pt2, 255, max(3, wall_thickness))

    close_kernel = np.ones((12, 12), np.uint8)
    wall_mask_closed = cv2.morphologyEx(wall_mask, cv2.MORPH_CLOSE,
                                         close_kernel, iterations=2)
    wall_mask_closed = cv2.dilate(wall_mask_closed,
                                   np.ones((5, 5), np.uint8), iterations=2)

    inv_mask = cv2.bitwise_not(wall_mask_closed)

    contours, hier = cv2.findContours(inv_mask, cv2.RETR_CCOMP,
                                       cv2.CHAIN_APPROX_SIMPLE)

    roi_area = roi_w * roi_h
    rooms = []
    PALETTE = [
        (255,  80,  80), ( 80, 160, 255), ( 80, 255, 160),
        (255, 200,  80), (200,  80, 255), (255,  80, 200),
        ( 80, 220, 220), (255, 140,  50), (160, 255,  80),
        (220, 180, 255),
    ]

    overlay = annotated.copy()
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if roi_area * 0.01 < area < roi_area * 0.85:
            x, y, w_cnt, h_cnt = cv2.boundingRect(cnt)

            cnt_shifted = cnt.copy()
            cnt_shifted[:, :, 0] += roi_x
            cnt_shifted[:, :, 1] += roi_y

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            aspect = round(w_cnt / h_cnt, 2) if h_cnt > 0 else 1.0
            label = _classify_room(w_cnt, h_cnt, area, roi_w, roi_h, len(rooms))

            rooms.append({
                "id": len(rooms) + 1,
                "label": label,
                "bbox": {
                    "x": int(x + roi_x), "y": int(y + roi_y),
                    "w": int(w_cnt), "h": int(h_cnt)
                },
                "area_px": int(area),
                "aspect_ratio": aspect,
                "centroid": [int(x + w_cnt / 2 + roi_x), int(y + h_cnt / 2 + roi_y)],
                "poly_pts": len(approx),
            })
            col = PALETTE[len(rooms) % len(PALETTE)]
            cv2.fillPoly(overlay, [cnt_shifted], col)
            cv2.drawContours(annotated, [cnt_shifted], -1, (30, 30, 200), 2)
            cx = x + w_cnt // 2 + roi_x
            cy = y + h_cnt // 2 + roi_y
            cv2.putText(annotated, f"R{len(rooms)}", (cx - 12, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 160), 2)

    cv2.addWeighted(overlay, 0.18, annotated, 0.82, 0, annotated)

    # ── Opening Detection ───────────────────────────────────────────────────
    openings = _detect_openings(walls, wall_mask, roi_x, roi_y, roi_w, roi_h)

    for op in openings:
        cv2.line(annotated,
                 (op["x1"], op["y1"]), (op["x2"], op["y2"]),
                 (0, 255, 255), 3)

    # ── Corner / Junction Detection & Classification ────────────────────────
    junctions = _detect_junctions(walls)

    # ── Scale Estimation ────────────────────────────────────────────────────
    px_per_m = _estimate_scale(rooms, roi_w, roi_h)

    for ww in walls:
        ww["length_m"] = round(ww["length_px"] / px_per_m, 2)

    # ── Build outer boundary box ─────────────────────────────────────────────
    outer_box = _detect_outer_boundary(walls, orig_w, orig_h)

    # ── Legend overlay ─────────────────────────────────────────────────────
    _draw_legend(annotated, len(walls), len(rooms), len(junctions), len(openings))

    parsed_data = {
        "image_size": {"w": orig_w, "h": orig_h},
        "roi": {"x": roi_x, "y": roi_y, "w": roi_w, "h": roi_h},
        "scale": {"px_per_m": round(px_per_m, 2), "note": "heuristic estimate"},
        "walls": walls,
        "wall_summary": {
            "total": len(walls),
            "horizontal": len(h_walls),
            "vertical": len(v_walls),
            "diagonal": len(d_walls),
            "total_length_px": int(sum(w["length_px"] for w in walls)),
            "total_length_m": round(sum(w["length_px"] for w in walls) / px_per_m, 2),
        },
        "rooms": rooms,
        "room_count": len(rooms),
        "openings": openings,
        "opening_count": len(openings),
        "junctions": junctions[:200],
        "junction_count": len(junctions),
        "outer_boundary": outer_box,
    }

    return parsed_data, annotated


# ─── Opening detection ────────────────────────────────────────────────────

def _detect_openings(walls, wall_mask, roi_x, roi_y, roi_w, roi_h):
    """
    Detect openings (doors/windows) by finding gaps between wall endpoints
    that are close but not connected.
    """
    openings = []
    endpoints = []

    for w in walls:
        endpoints.append((w["x1"] - roi_x, w["y1"] - roi_y, w["id"], "start"))
        endpoints.append((w["x2"] - roi_x, w["y2"] - roi_y, w["id"], "end"))

    min_gap = max(8, int(min(roi_w, roi_h) * 0.02))
    max_gap = int(min(roi_w, roi_h) * 0.12)

    for i, (x1, y1, id1, _) in enumerate(endpoints):
        for j, (x2, y2, id2, _) in enumerate(endpoints):
            if j <= i or id1 == id2:
                continue
            dist = _length(x1, y1, x2, y2)
            if min_gap < dist < max_gap:
                w1 = next((w for w in walls if w["id"] == id1), None)
                w2 = next((w for w in walls if w["id"] == id2), None)
                if w1 is None or w2 is None:
                    continue
                if w1["orientation"] == w2["orientation"]:
                    mx, my = int((x1 + x2) / 2), int((y1 + y2) / 2)
                    if 0 <= mx < roi_w and 0 <= my < roi_h:
                        if wall_mask[my, mx] == 0:
                            op_type = "door" if dist < max_gap * 0.6 else "window"
                            openings.append({
                                "id": len(openings),
                                "x1": int(x1 + roi_x), "y1": int(y1 + roi_y),
                                "x2": int(x2 + roi_x), "y2": int(y2 + roi_y),
                                "type": op_type,
                                "width_px": round(dist, 1),
                            })

    # Deduplicate
    deduped = []
    for op in openings:
        is_dup = False
        for existing in deduped:
            d = _length(op["x1"], op["y1"], existing["x1"], existing["y1"])
            if d < min_gap:
                is_dup = True
                break
        if not is_dup:
            deduped.append(op)

    return deduped


def _detect_junctions(walls):
    """
    Detect wall junctions by finding endpoints that are shared between
    multiple walls (within tolerance).
    """
    junctions = []
    tol = 15

    all_endpoints = []
    for w in walls:
        all_endpoints.append((w["x1"], w["y1"], w["id"]))
        all_endpoints.append((w["x2"], w["y2"], w["id"]))

    visited = set()
    for i, (x1, y1, wid1) in enumerate(all_endpoints):
        if i in visited:
            continue
        cluster_wall_ids = {wid1}
        cluster_x = [x1]
        cluster_y = [y1]

        for j, (x2, y2, wid2) in enumerate(all_endpoints):
            if j <= i or j in visited:
                continue
            if _length(x1, y1, x2, y2) < tol:
                cluster_wall_ids.add(wid2)
                cluster_x.append(x2)
                cluster_y.append(y2)
                visited.add(j)

        visited.add(i)
        n_walls = len(cluster_wall_ids)
        if n_walls >= 2:
            avg_x = int(np.mean(cluster_x))
            avg_y = int(np.mean(cluster_y))
            jtype = "X" if n_walls >= 4 else ("T" if n_walls == 3 else "L")
            junctions.append({"x": avg_x, "y": avg_y, "type": jtype})

    return junctions


# ─── helpers ───────────────────────────────────────────────────────────────

def _classify_room(w, h, area_px, img_w, img_h, idx):
    ratio = area_px / (img_w * img_h)
    aspect = w / h if h else 1
    labels = [
        "Living Room / Great Room",
        "Master Bedroom",
        "Bedroom",
        "Kitchen",
        "Dining Area",
        "Bathroom",
        "Laundry",
        "Foyer / Entry",
        "Corridor / Passage",
        "Storage / Utility",
    ]
    if ratio > 0.22:   return "Living Room / Great Room"
    if ratio > 0.14:   return "Master Bedroom"
    if ratio > 0.08:   return "Bedroom"
    if ratio > 0.05:   return "Kitchen / Dining"
    if aspect > 2.8 or aspect < 0.35:  return "Corridor / Passage"
    if ratio < 0.025:  return "Bathroom / WC"
    return labels[idx % len(labels)]


def _estimate_scale(rooms, img_w, img_h):
    if not rooms:
        return max(img_w, img_h) / 12
    largest = max(rooms, key=lambda r: r["area_px"])
    px_dim = max(largest["bbox"]["w"], largest["bbox"]["h"])
    assumed_m = 5.5
    return px_dim / assumed_m if px_dim > 0 else max(img_w, img_h) / 12


def _detect_outer_boundary(walls, img_w, img_h):
    """Return approximate outer boundary as bounding box of all wall endpoints."""
    if not walls:
        return {"x": 0, "y": 0, "w": img_w, "h": img_h}
    xs = [w["x1"] for w in walls] + [w["x2"] for w in walls]
    ys = [w["y1"] for w in walls] + [w["y2"] for w in walls]
    x0, y0 = min(xs), min(ys)
    x1, y1 = max(xs), max(ys)
    return {"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)}


def _draw_legend(img, wall_cnt, room_cnt, junc_cnt, open_cnt):
    items = [
        ("Walls",     str(wall_cnt), (0, 200, 255)),
        ("Rooms",     str(room_cnt), (30,  30, 200)),
        ("Junctions", str(junc_cnt), (0,  200, 100)),
        ("Openings",  str(open_cnt), (0,  240, 240)),
    ]
    bx, by, bw = 8, 8, 200
    bh = 14 + len(items) * 20
    cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (15, 15, 15), -1)
    cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (80, 80, 80), 1)
    for i, (lbl, val, col) in enumerate(items):
        ty = by + 22 + i * 20
        cv2.putText(img, f"{lbl}: {val}", (bx + 8, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, col, 1, cv2.LINE_AA)
