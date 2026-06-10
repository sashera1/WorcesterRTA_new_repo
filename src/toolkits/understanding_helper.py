from pathlib import Path
import duckdb
import csv
from collections import defaultdict
"""helpful as i realized
recently that a lot of my code/plans were
based on assuptions that could be false, in addition
there are things that i can't tell from looking but
if i knew, i could save a lot of time/get more accurate results, etc
thus these functions are here to help


also started using duckdb instead of clunky ole csv reader
o boy the amount of refactoring imma need to do 
is growing every day """

src_dir = "data/raw/transitland_wrta_latest"
corridors_ref_dir = "data/processed/stops_organized_data"

def check_route_shapes_unique_by_direction(trips_txt_path: str | Path) -> set[tuple[str, str]] | None:
    """
    Checks if any (route_id, direction_id) has multiple shape_ids using DuckDB.
    Returns a set of violator tuples, or None if all are unique.
    """


    query = f"""
        SELECT route_id, CAST(direction_id AS VARCHAR)
        FROM read_csv('{trips_txt_path}')
        WHERE route_id IS NOT NULL 
          AND direction_id IS NOT NULL 
          AND shape_id IS NOT NULL
        GROUP BY route_id, direction_id
        HAVING COUNT(DISTINCT shape_id) > 1
    """

    results = duckdb.query(query).fetchall()
    
    return set(results) if results else None

# results = check_route_shapes_unique_by_direction(f"{src_dir}/trips.txt")    
# if results:
#     for violater in results:
#         print(violater)


def verify_trip_pairs_covering_corridor(
    corridor_paths_with_routes: dict[str, list[str]], 
    trips_path: str, 
    stop_times_path: str):
    
    # 1. Load Corridor Stops
    # { path: {"routes": ['19','27'], "stops": {'stopA', 'stopB'}} }
    corridors_data = {}
    target_routes = set()
    for path, route_list in corridor_paths_with_routes.items():
        required_stops = set()
        with open(path, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                required_stops.add(row['stop_id'])
        
        corridors_data[path] = {"routes": route_list, "stops": required_stops}
        target_routes.update(route_list)

    # 2. Map trips to routes and directions (ONLY for routes we care about to save memory)
    # trip_info[trip_id] = (route_id, direction_id)
    trip_info = {}
    with open(trips_path, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['route_id'] in target_routes:
                trip_info[row['trip_id']] = (row['route_id'], row['direction_id'])

    # 3. Stream stop_times.txt to collect stop sets for each trip
    # trip_stops[trip_id] = {'stopA', 'stopB', ...}
    trip_stops = defaultdict(set)
    with open(stop_times_path, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            trip_id = row['trip_id']
            # Only track trips that belong to our target routes
            if trip_id in trip_info:
                trip_stops[trip_id].add(row['stop_id'])

    # 4. Find the Champion Pairs and Verify
    results = {}

    for path, data in corridors_data.items():
        required_stops = data["stops"]
        route_list = data["routes"]
        
        # We try to find a valid pair for ANY of the routes associated with this corridor
        pair_found = False
        
        for route_id in route_list:
            if pair_found: break
                
            # Filter trips for this specific route, separated by direction
            dir_0_trips = [t_id for t_id, info in trip_info.items() if info == (route_id, '0') and t_id in trip_stops]
            dir_1_trips = [t_id for t_id, info in trip_info.items() if info == (route_id, '1') and t_id in trip_stops]

            if not dir_0_trips or not dir_1_trips:
                continue # Route is missing a direction in the data

            # The "Champion" is the trip with the maximum number of stops
            champ_0 = max(dir_0_trips, key=lambda t: len(trip_stops[t]))
            champ_1 = max(dir_1_trips, key=lambda t: len(trip_stops[t]))

            # Combine the stops of both champions
            combined_stops = trip_stops[champ_0].union(trip_stops[champ_1])

            # Check if this combined super-set covers the corridor
            if required_stops.issubset(combined_stops):
                results[path] = {
                    "route_id": route_id,
                    "direction_0_trip": champ_0,
                    "direction_1_trip": champ_1
                }
                pair_found = True

    return results


corridors = {
        f'{corridors_ref_dir}/Orange_corridor_shared_stops.csv':["19","27","33"], 
        f'{corridors_ref_dir}/Blue_corridor_shared_stops.csv':["5","12"], 
        f'{corridors_ref_dir}/Green_corridor_shared_stops.csv':["23","26"]
    }
results = verify_trip_pairs_covering_corridor(corridors,f"{src_dir}/trips.txt",f"{src_dir}/stop_times.txt")
for k,v in results.items():
    print(f"{k} route: {v['route_id']}: {v['direction_0_trip']}, {v['direction_1_trip']}")

"""
results:
Orange route: 19 : 0_1328542, 0_1328536
Blue route: 5 : 2_7328185, 1_6327651
Green route: 23 : 1_6327887, 1_6327879
"""



