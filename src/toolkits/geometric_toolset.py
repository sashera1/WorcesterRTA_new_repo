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
        stops_in:list[str],
        coordinates_in:list[tuple[float,float]],
        threshold_meters:int=0,
        consolidation_limit:int=2)->dict[tuple[str, ...], tuple[float, float]]:

    """unsure if works with refactor BUT
    NOTE this whole code may be unneccesary LOL"""
    
    #input tuple[lat,long] pyproj needs [long,lat]
    points_degrees = MultiPoint([Point(item[1], item[0]) for item in coordinates_in])
    points_meters = transform(project_from_deg_to_meters, points_degrees)#convert to list[tuple[float,float]]
    points_meters = [(point.x, point.y) for point in points_meters.geoms]

    working_data = dict(zip([(stop,) for stop in stops_in],points_meters))

    while True:
        if len(working_data) < 2:
            break
        
        pq = []
        stops_list = list(working_data.keys())

        if debug_mode: print("building batch")

        # 1. Build the priority queue: Calculate distances once per batch
        for i in range(len(stops_list)):
            for j in range(i + 1, len(stops_list)):
                key_i = stops_list[i]
                key_j = stops_list[j]
                
                # Check your consolidation limit first to save math
                if len(key_i) + len(key_j) <= consolidation_limit:
                    distance = dist(working_data[key_i], working_data[key_j])
                    
                    # Only add to queue if under or equal to threshold
                    if distance <= threshold_meters:
                        # Push to heap: Python tuples natively sort by the first element (distance)
                        heapq.heappush(pq, (distance, key_i, key_j))

        # If no pairs met the threshold, clustering is completely finished
        if not pq:
            if debug_mode: print("no more point merges under conditions")
            break

        next_working_data = {}
        merged_keys = set()

        # 2. Process the queue, popping the absolute shortest distances first
        while pq:
            distance, key_i, key_j = heapq.heappop(pq)

            # Skip if either point was already involved in a merge during this pass
            if key_i in merged_keys or key_j in merged_keys:
                continue

            # Merge the pair
            coords_i = working_data[key_i]
            coords_j = working_data[key_j]

            weight_i = len(key_i)
            weight_j = len(key_j)
            total_weight = weight_i + weight_j

            new_x = (weight_i * coords_i[0] + weight_j * coords_j[0]) / total_weight
            new_y = (weight_i * coords_i[1] + weight_j * coords_j[1]) / total_weight

            new_key = key_i + key_j
            new_coords = (new_x, new_y)

            # Add to the new dictionary
            next_working_data[new_key] = new_coords
            
            # Mark both original points as successfully merged
            merged_keys.add(key_i)
            merged_keys.add(key_j)

        # 3. Carry over all unmerged points to the next iteration
        for key, coords in working_data.items():
            if key not in merged_keys:
                next_working_data[key] = coords

        # Overwrite working_data to start the next batch pass
        working_data = next_working_data

    final_points_meters = MultiPoint([Point(coords[0], coords[1]) for coords in working_data.values()])
    final_points_degrees = transform(project_from_meters_to_degrees, final_points_meters)
    
    final_data = {}
    # Zip the dictionary keys together with the transformed Shapely points
    for key, point_deg in zip(working_data.keys(), final_points_degrees.geoms):
        # pyproj returns (lon, lat) through Shapely. We swap back to (lat, lon) for our output.
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


