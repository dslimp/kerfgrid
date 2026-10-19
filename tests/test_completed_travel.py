import math
import re

from shapely.geometry import LineString, Point as ShapePoint, Polygon, box

from plasma_cam.cam.options import LeadOverride, QtPlasmaCOptions, TravelObstacle
from plasma_cam.cam.travel import contour_obstacle, safe_rapid_lines, rapid_distance
from plasma_cam.model import CircleContour, LineSegment, PathContour, Point
from plasma_cam.post import generate_gcode, planned_cut_sequence
from plasma_cam.application.gcode_simulation import segments_from_gcode


def path(name, points, *, closed=True, kind='outer'):
    points = [Point(*p) for p in points]
    return PathContour(name, tuple(LineSegment(a, b) for a, b in zip(points, points[1:] + (points[:1] if closed else []))), kind)


def rapid_points(start, lines):
    output = [start]
    for line in lines:
        if line.startswith('G0 '):
            words = dict(re.findall(r'([XY])(-?[\d.]+)', line))
            output.append(Point(float(words['X']), float(words['Y'])))
    return output


def test_completed_part_under_start_is_not_ignored_for_whole_move():
    obstacle = contour_obstacle(path('cut_part', [(0, 0), (20, 0), (20, 20), (0, 20)]))
    start, end = Point(0, 10), Point(50, 10)
    lines = safe_rapid_lines(start, end, [obstacle], QtPlasmaCOptions(travel_clearance=2, travel_bounds=(-10, -10, 100, 40)), None)
    assert not any(line.startswith('M0') for line in lines)
    points = rapid_points(start, lines)
    assert len(points) > 2
    for a, b in zip(points, points[1:]):
        assert LineString([(a.x, a.y), (b.x, b.y)]).intersection(box(0, 0, 20, 20).buffer(-0.001)).is_empty


def test_start_in_clearance_envelope_exits_outwards_before_detour():
    obstacle = TravelObstacle(0, 0, 20, 20, completed=True)
    start, end = Point(25, 10), Point(-20, 10)
    lines = safe_rapid_lines(start, end, [obstacle], QtPlasmaCOptions(travel_clearance=8), None)
    assert not any(line.startswith('M0') for line in lines)
    points = rapid_points(start, lines)
    assert points[1].x > start.x
    for a, b in zip(points, points[1:]):
        assert LineString([(a.x, a.y), (b.x, b.y)]).intersection(box(0, 0, 20, 20).buffer(-0.001)).is_empty


def test_polygon_avoids_unnecessary_rectangle_detour():
    obstacle = contour_obstacle(path('triangle', [(0, 0), (100, 0), (0, 100)]))
    start, end = Point(-10, 120), Point(120, -10)
    lines = safe_rapid_lines(start, end, [obstacle], QtPlasmaCOptions(travel_clearance=0), None)
    assert len(lines) == 1 and lines[0].startswith('G0 X120 Y-10')


def test_circle_obstacle_conservatively_covers_actual_contour():
    obstacle = contour_obstacle(CircleContour('slug', Point(20, 20), 10, 'hole'))
    shape = Polygon([(p.x, p.y) for p in obstacle.outline]).buffer(1e-8)
    for i in range(720):
        angle = math.tau * i / 720
        assert shape.covers(ShapePoint(20 + 10 * math.cos(angle), 20 + 10 * math.sin(angle)))


def test_departure_from_hole_slug_uses_short_egress_then_avoids_it():
    obstacle = contour_obstacle(CircleContour('slug', Point(20, 20), 10, 'hole'))
    start, end = Point(20, 20), Point(60, 60)
    lines = safe_rapid_lines(start, end, [obstacle], QtPlasmaCOptions(travel_clearance=2), None)
    assert not any(line.startswith('M0') for line in lines)
    assert len(rapid_points(start, lines)) >= 3


def test_fixed_obstacle_cannot_be_exempted_by_endpoint_overlap():
    lines = safe_rapid_lines(Point(5, 5), Point(50, 5), [TravelObstacle(0, 0, 10, 10)], QtPlasmaCOptions(), None)
    assert lines[0].startswith('M0 ')
    assert 'WARNING: safe travel' in lines[-1]


def test_direct_mode_skips_routes_and_operator_pauses():
    lines = safe_rapid_lines(Point(0, 0), Point(50, 0), [TravelObstacle(10, -10, 20, 10)], QtPlasmaCOptions(safe_travel=False), None)
    assert lines == ['G0 X50 Y0']


def test_unavoidable_crossing_has_pause_even_without_optional_comments():
    options = QtPlasmaCOptions(travel_bounds=(0, 0, 50, 50), include_comments=False, travel_clearance=0)
    lines = safe_rapid_lines(Point(0, 20), Point(50, 20), [TravelObstacle(20, -1, 30, 51)], options, 'pierce')
    assert lines[0].startswith('M0 ')
    assert 'WARNING: safe travel' in lines[-1]
    simulation = segments_from_gcode('\n'.join(lines), cut_feed_rate_mm_min=900, rapid_rate_mm_min=8000)
    assert simulation[0]['safe_travel_warning']
    assert simulation[0]['operator_pause_before']


def test_open_cut_does_not_create_a_separated_part_obstacle():
    contour = path('open', [(10, 10), (40, 10)], closed=False)
    assert contour_obstacle(contour) is None
    assert 'M0' not in generate_gcode([contour], QtPlasmaCOptions(lead_in_mode='none'))


def test_rounded_rapid_segments_keep_requested_clearance():
    obstacle = TravelObstacle(10.1234, 0, 20.5678, 30)
    options = QtPlasmaCOptions(travel_clearance=3.5, travel_bounds=(0, 0, 60, 60))
    start, end = Point(0, 10), Point(50, 10)
    lines = safe_rapid_lines(start, end, [obstacle], options, None)
    assert not any(line.startswith('M0') for line in lines)
    for a, b in zip(rapid_points(start, lines), rapid_points(start, lines)[1:]):
        segment = LineString([(a.x, a.y), (b.x, b.y)])
        assert segment.distance(box(10.1234, 0, 20.5678, 30)) >= 3.5 - 1e-6
    assert rapid_distance(start, end, [obstacle], options) > start.distance_to(end)


def test_zero_decimal_precision_preserves_trailing_integer_zeroes():
    from plasma_cam.cam.gcode import format_number

    assert format_number(100, 0) == '100'
    assert format_number(-20, 0) == '-20'
    assert format_number(10.5, 1) == '10.5'


def test_safe_order_keeps_part_with_trapped_edge_exit_until_last():
    corner = path('corner_1_outer', [(0, 0), (20, 0), (20, 20), (0, 20)])
    other = path('other_1_outer', [(50, 50), (60, 50), (60, 60), (50, 60)])
    options = QtPlasmaCOptions(lead_in_mode='none', travel_clearance=2,
                              travel_bounds=(0, 0, 100, 100), cut_order_strategy='lower_left',
                              lead_overrides=(LeadOverride('corner_1_outer', start_x=0, start_y=0),))
    assert [item['name'] for item in planned_cut_sequence([corner, other], options)] == ['other_1_outer', 'corner_1_outer']
    assert 'M0 ' not in generate_gcode([corner, other], options)


def test_ungrouped_order_keeps_own_hole_before_outer():
    outer = path('plate_1_outer', [(0, 0), (100, 0), (100, 100), (0, 100)])
    hole = CircleContour('plate_1_hole', Point(80, 80), 10, 'hole')
    options = QtPlasmaCOptions(keep_part_contours_together=False, safe_travel=False, lead_in_mode='none')
    assert [item['name'] for item in planned_cut_sequence([outer, hole], options)] == ['plate_1_hole', 'plate_1_outer']


def test_ungrouped_order_cuts_filler_before_its_surrounding_hole():
    outer = path('plate_1_outer', [(0, 0), (100, 0), (100, 100), (0, 100)])
    hole = path('plate_1_hole', [(10, 10), (90, 10), (90, 90), (10, 90)], kind='hole')
    filler = path('token_1_outer', [(40, 40), (60, 40), (60, 60), (40, 60)])
    options = QtPlasmaCOptions(keep_part_contours_together=False, safe_travel=False, lead_in_mode='none')
    assert [item['name'] for item in planned_cut_sequence([outer, hole, filler], options)] == ['token_1_outer', 'plate_1_hole', 'plate_1_outer']


def test_ungrouped_order_preserves_manual_part_group_ranks():
    first = CircleContour('plate_1_outer', Point(20, 20), 5, 'outer')
    second = CircleContour('plate_2_outer', Point(80, 80), 5, 'outer')
    options = QtPlasmaCOptions(keep_part_contours_together=False, safe_travel=False,
                              lead_in_mode='none', cut_order_groups=('plate_2', 'plate_1'))
    assert [item['name'] for item in planned_cut_sequence([first, second], options)] == ['plate_2_outer', 'plate_1_outer']


def test_unresolved_rapid_comments_cannot_inject_gcode():
    lines = safe_rapid_lines(Point(5, 5), Point(50, 5), [TravelObstacle(0, 0, 10, 10)], QtPlasmaCOptions(), 'part) M3 (')
    assert all(line.count('(') == 1 and line.count(')') == 1 for line in lines)
    assert not any('M3' in re.sub(r'\([^)]*\)', '', line) for line in lines)


def test_gcode_line_sanitizes_operator_names_in_comments():
    from plasma_cam.cam.gcode import gcode_line

    line = gcode_line('G0 X10 Y20', 'part)\nM3 (other', QtPlasmaCOptions())
    assert line == 'G0 X10 Y20 (part M3 other)'
