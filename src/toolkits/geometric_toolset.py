from src.config import center_coords, debug_mode
from pyproj import CRS, Transformer
from shapely.geometry import Point, MultiPoint
from shapely.ops import transform
from math import dist
import heapq

CRS_meters = CRS(proj="aeqd", lat_0=center_coords[0], lon_0=center_coords[1], datum="WGS84")
CRS_degrees = CRS("EPSG:4326")

#always_xy = true dictates we will always be applying transformations and getting back longitude, lattitude
project_from_deg_to_meters = Transformer.from_crs(CRS_degrees, CRS_meters, always_xy=True).transform
project_from_meters_to_degrees = Transformer.from_crs(CRS_meters, CRS_degrees, always_xy=True).transform

def consolidate_stops(
        stops_in: list[str],
        coordinates_in: list[tuple[float, float]],
        stops_in_loop_ignore: list[str],
        threshold_meters: int = 0,
        consolidation_limit: int = 2) -> dict[tuple[str, ...], tuple[float, float]]:
    
    # 1. Transform coordinates to meters
    points_degrees = MultiPoint([Point(item[1], item[0]) for item in coordinates_in])
    points_meters = transform(project_from_deg_to_meters, points_degrees)
    points_meters = [(point.x, point.y) for point in points_meters.geoms]

    working_data = dict(zip([(stop,) for stop in stops_in], points_meters))

    # 2. Extract and preserve "ignored" stops
    stop_in_loop_data = {}
    for stop_in_loop in stops_in_loop_ignore:
        if (stop_in_loop,) in working_data:
            stop_in_loop_data[stop_in_loop] = working_data[(stop_in_loop,)]
            del working_data[(stop_in_loop,)]

    # 3. Initialize structures for Lazy Deletion Queue
    active_nodes = set(working_data.keys())
    pq = []
    
    stops_list = list(active_nodes)

    if debug_mode: print("Building initial priority queue O(N^2)")

    # Build the Priority Queue ONCE
    for i in range(len(stops_list)):
        for j in range(i + 1, len(stops_list)):
            key_i = stops_list[i]
            key_j = stops_list[j]
            
            if len(key_i) + len(key_j) <= consolidation_limit:
                distance = dist(working_data[key_i], working_data[key_j])
                if distance <= threshold_meters:
                    heapq.heappush(pq, (distance, key_i, key_j))

    # 4. Process the Queue continuously
    while pq:
        distance, key_i, key_j = heapq.heappop(pq)

        # LAZY DELETION: If either node was already merged into something else, discard this pair
        if key_i not in active_nodes or key_j not in active_nodes:
            continue

        # Valid merge! Remove old nodes from active set
        active_nodes.remove(key_i)
        active_nodes.remove(key_j)

        coords_i = working_data[key_i]
        coords_j = working_data[key_j]

        weight_i = len(key_i)
        weight_j = len(key_j)
        total_weight = weight_i + weight_j

        new_x = (weight_i * coords_i[0] + weight_j * coords_j[0]) / total_weight
        new_y = (weight_i * coords_i[1] + weight_j * coords_j[1]) / total_weight

        new_key = key_i + key_j
        new_coords = (new_x, new_y)

        # Store the new node in our global dictionary
        working_data[new_key] = new_coords

        # DYNAMIC INSERTION: Calculate distances ONLY for the newly created node
        for other_key in active_nodes:
            if len(new_key) + len(other_key) <= consolidation_limit:
                new_distance = dist(working_data[new_key], working_data[other_key])
                if new_distance <= threshold_meters:
                    heapq.heappush(pq, (new_distance, new_key, other_key))

        # Add the new node to the active set so it can be merged in future iterations
        active_nodes.add(new_key)

    # 5. Cleanup: Build final_working_data containing only the active (unmerged) nodes
    final_working_data = {k: working_data[k] for k in active_nodes}

    # Add the ignored stops back in
    for ignored, ignored_coords in stop_in_loop_data.items():
        final_working_data[(ignored,)] = ignored_coords

    # 6. Transform back to degrees
    final_points_meters = MultiPoint([Point(coords[0], coords[1]) for coords in final_working_data.values()])
    final_points_degrees = transform(project_from_meters_to_degrees, final_points_meters)
    
    final_data = {}
    for key, point_deg in zip(final_working_data.keys(), final_points_degrees.geoms):
        # Shapely/pyproj outputs (lon, lat); swap back to (lat, lon)
        final_data[key] = (point_deg.y, point_deg.x)

    return final_data

def pad_boundry(xlim:tuple[float, float], ylim:tuple[float, float], padding_factor=0.10):
    x_range = xlim[1] - xlim[0]
    y_range = ylim[1] - ylim[0]
    
    padded_xlim = (xlim[0] - (x_range * padding_factor), 
                   xlim[1] + (x_range * padding_factor))
    
    padded_ylim = (ylim[0] - (y_range * padding_factor), 
                   ylim[1] + (y_range * padding_factor))
    
    return padded_xlim,padded_ylim


