export function completedCutPaths(points) {
  const paths = [];
  let current = null;
  for (let index = 1; index < points.length; index += 1) {
    if (points[index].type !== "cut") {
      current = null;
      continue;
    }
    if (!current) {
      current = [points[index - 1]];
      paths.push(current);
    }
    current.push(points[index]);
  }
  return paths;
}

export function pointsUntilTime(points, time) {
  if (!points.length) return [];
  const output = [];
  for (const point of points) {
    if (point.t <= time) output.push(point);
    else break;
  }
  const current = pointAtTime(points, time);
  if (current && (!output.length || output[output.length - 1].t < time)) output.push(current);
  return output;
}

export function pointAtTime(points, time) {
  if (!points.length) return null;
  if (time <= points[0].t) return points[0];
  const last = points[points.length - 1];
  if (time >= last.t) return last;
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    if (point.t >= time) {
      const previous = points[index - 1];
      const ratio = (time - previous.t) / (point.t - previous.t || 1);
      return { ...point, x: previous.x + (point.x - previous.x) * ratio, y: previous.y + (point.y - previous.y) * ratio, t: time };
    }
  }
  return last;
}
