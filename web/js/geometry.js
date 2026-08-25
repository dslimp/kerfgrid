export function normalizeAngle(degrees) {
  const value = degrees % 360;
  return value < 0 ? value + 360 : value;
}

export function normalizeAllowedRotations(values, fallback = [0, 90, 180, 270]) {
  const source = Array.isArray(values) && values.length ? values : fallback;
  const output = [];
  for (const value of source) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) continue;
    const angle = normalizeAngle(numeric);
    if (!output.some((existing) => Math.abs(existing - angle) < 0.001)) {
      output.push(angle);
    }
  }
  return output.length ? output : [...fallback];
}

export function rotateLocal(point, degrees) {
  const angle = (degrees * Math.PI) / 180;
  return {
    x: point.x * Math.cos(angle) - point.y * Math.sin(angle),
    y: point.x * Math.sin(angle) + point.y * Math.cos(angle),
  };
}

export function transformLocal(point, placement) {
  const rotated = rotateLocal(point, placement.rotation_deg || 0);
  return {
    x: placement.dx + rotated.x,
    y: placement.dy + rotated.y,
  };
}

export function transformWorldToLocal(point, placement) {
  return rotateLocal(
    {
      x: point.x - placement.dx,
      y: point.y - placement.dy,
    },
    -(placement.rotation_deg || 0)
  );
}

export function partContours(part) {
  if (Array.isArray(part.contours) && part.contours.length) {
    return part.contours;
  }
  const contours = [];
  if (part.outer) {
    contours.push({
      type: "circle",
      kind: "outer",
      name: `${part.name}_outer`,
      center: { x: Number(part.outer.x || 0), y: Number(part.outer.y || 0) },
      radius_mm: Number(part.outer.radius_mm || part.outer.radius || 0),
    });
  }
  for (const [index, hole] of (part.holes || []).entries()) {
    contours.push({
      type: "circle",
      kind: "hole",
      name: `${part.name}_hole_${index + 1}`,
      center: { x: Number(hole.x || 0), y: Number(hole.y || 0) },
      radius_mm: Number(hole.radius_mm || hole.radius || 0),
    });
  }
  return contours;
}

export function contourPoints(contour) {
  if (contour.type === "circle") {
    const center = contour.center || { x: contour.x || 0, y: contour.y || 0 };
    const radius = Number(contour.radius_mm || contour.radius || 0);
    const steps = 96;
    const points = [];
    for (let index = 0; index < steps; index += 1) {
      const angle = (Math.PI * 2 * index) / steps;
      points.push({
        x: Number(center.x || 0) + Math.cos(angle) * radius,
        y: Number(center.y || 0) + Math.sin(angle) * radius,
      });
    }
    return points;
  }
  const output = [];
  for (const segment of contour.segments || []) {
    const points = segmentPoints(segment);
    if (output.length && points.length && closePoints(output[output.length - 1], points[0])) {
      output.push(...points.slice(1));
    } else {
      output.push(...points);
    }
  }
  if (output.length > 1 && closePoints(output[0], output[output.length - 1])) {
    output.pop();
  }
  return output;
}

export function segmentPoints(segment) {
  if (segment.type !== "arc") {
    return [segment.start, segment.end];
  }
  const start = segment.start;
  const end = segment.end;
  const center = segment.center;
  const radius = Math.hypot(start.x - center.x, start.y - center.y);
  if (!radius) return [start, end];
  let startAngle = Math.atan2(start.y - center.y, start.x - center.x);
  let endAngle = Math.atan2(end.y - center.y, end.x - center.x);
  if (segment.clockwise) {
    if (endAngle >= startAngle) endAngle -= Math.PI * 2;
  } else if (endAngle <= startAngle) {
    endAngle += Math.PI * 2;
  }
  const sweep = endAngle - startAngle;
  const steps = Math.max(8, Math.ceil((Math.abs(sweep) * radius) / 3));
  const points = [];
  for (let index = 0; index <= steps; index += 1) {
    const angle = startAngle + (sweep * index) / steps;
    points.push({
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius,
    });
  }
  return points;
}

export function closePoints(left, right) {
  return Math.hypot(left.x - right.x, left.y - right.y) <= 0.05;
}

export function point(x, y) {
  return { x, y };
}

export function lineSegment(start, end) {
  return { type: "line", start, end };
}

export function circleContour(name, x, y, radius, kind = "hole") {
  return {
    type: "circle",
    kind,
    name,
    center: point(x, y),
    radius_mm: radius,
  };
}

export function rectangleContour(name, width, height, kind = "outer") {
  const left = -width / 2;
  const right = width / 2;
  const bottom = -height / 2;
  const top = height / 2;
  const corners = [
    point(left, bottom),
    point(right, bottom),
    point(right, top),
    point(left, top),
  ];
  return {
    type: "path",
    kind,
    name,
    segments: [
      lineSegment(corners[0], corners[1]),
      lineSegment(corners[1], corners[2]),
      lineSegment(corners[2], corners[3]),
      lineSegment(corners[3], corners[0]),
    ],
  };
}

export function boundedHoleRadius(diameter, outerRadius, centerRadius = 0) {
  const radius = Math.max(0, Number(diameter || 0) / 2);
  const available = Math.max(0, outerRadius - centerRadius - 1);
  return Math.min(radius, available);
}

export function partBounds(part) {
  return boundsForPoints(partContours(part).flatMap((contour) => contourPoints(contour)));
}

export function rotatedPartBounds(part, degrees) {
  return boundsForPoints(
    partContours(part)
      .flatMap((contour) => contourPoints(contour))
      .map((item) => rotateLocal(item, degrees || 0))
  );
}

export function placementWorldBounds(part, placement) {
  const bounds = rotatedPartBounds(part, placement.rotation_deg || 0);
  return {
    minX: placement.dx + bounds.minX,
    minY: placement.dy + bounds.minY,
    maxX: placement.dx + bounds.maxX,
    maxY: placement.dy + bounds.maxY,
    width: bounds.width,
    height: bounds.height,
  };
}

export function mirrorContour(contour, mirrorX, oldPartName, newPartName) {
  const name = mirrorContourName(
    contour.name || `${oldPartName}_${contour.kind || "outer"}`,
    oldPartName,
    newPartName
  );
  if (contour.type === "circle") {
    const center = contour.center || { x: contour.x || 0, y: contour.y || 0 };
    return {
      ...contour,
      name,
      center: mirrorPoint(center, mirrorX),
    };
  }
  return {
    ...contour,
    name,
    segments: (contour.segments || []).map((segment) => mirrorSegment(segment, mirrorX)),
  };
}

export function mirrorContourName(name, oldPartName, newPartName) {
  const value = String(name || "");
  if (value.startsWith(`${oldPartName}_`)) {
    return `${newPartName}_${value.slice(oldPartName.length + 1)}`;
  }
  return `${value || "contour"}_mirrored`;
}

export function mirrorSegment(segment, mirrorX) {
  const mirrored = {
    ...segment,
    start: mirrorPoint(segment.start, mirrorX),
    end: mirrorPoint(segment.end, mirrorX),
  };
  if (segment.type === "arc") {
    mirrored.center = mirrorPoint(segment.center, mirrorX);
    mirrored.clockwise = !Boolean(segment.clockwise);
  }
  return mirrored;
}

export function mirrorPoint(item, mirrorX) {
  return {
    x: 2 * mirrorX - Number(item.x || 0),
    y: Number(item.y || 0),
  };
}

export function boxesOverlap(left, right, clearance = 0) {
  return !(
    left.maxX + clearance <= right.minX ||
    right.maxX + clearance <= left.minX ||
    left.maxY + clearance <= right.minY ||
    right.maxY + clearance <= left.minY
  );
}

export function boxInside(inner, outer, clearance = 0, epsilon = 1e-6) {
  return (
    inner.minX >= outer.minX + clearance - epsilon &&
    inner.minY >= outer.minY + clearance - epsilon &&
    inner.maxX <= outer.maxX - clearance + epsilon &&
    inner.maxY <= outer.maxY - clearance + epsilon
  );
}

export function zoneBounds(zone) {
  const minX = Number(zone.x_mm || 0);
  const minY = Number(zone.y_mm || 0);
  return {
    minX,
    minY,
    maxX: minX + Number(zone.width_mm || 0),
    maxY: minY + Number(zone.height_mm || 0),
  };
}

function boundsForPoints(points) {
  if (!points.length) {
    return { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 };
  }
  const minX = Math.min(...points.map((item) => item.x));
  const minY = Math.min(...points.map((item) => item.y));
  const maxX = Math.max(...points.map((item) => item.x));
  const maxY = Math.max(...points.map((item) => item.y));
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}
