import csv

"""
the point of this script is to get all stops by each route
and their coordinates"""

"""Corridors

Orange Corridor
Routes: 19, 27, 33
From: Central Hub → Curtis St
Shared stops: 16

Blue Corridor
Routes: 5, 12
From: Central Hub → Sunderland
Shared stops: 23

Green Corridor
Routes: 23, 26
From: Catherine → Lincoln Plaza
Shared stops: 13"""

def get_stop_ids_by_routes(routes : set|list) -> dict[str, set[str]]:
    """
    Params: 
    a set or list of route numbers (as strings or integers), specifying the routes from which to retreive stop ids

    Returns:
    a dict of route numbers (as strings) as keys and sets of stop ids (as strings) as values
    """
    trips_by_route = {}
    for route in routes:
        trips_by_route[route] = []
    
    with open("transitland_datasets/transitland_wrta_latest/trips.txt",'r') as trips:
        reader = csv.DictReader(trips)
        for row in reader:
            if row['route_id'] in trips_by_route.keys():
                trips_by_route[row['route_id']].append(row['trip_id'])

    stop_ids_by_route = {}
    for route in routes:
        stop_ids_by_route[route] = set()

    # takes a few sec to run
    # exponential time but for practical purposes,
    #linear as is bounded by set #of trips
    with open("transitland_datasets/transitland_wrta_latest/stop_times.txt",'r') as stop_times:
        reader = csv.DictReader(stop_times)
        for row in reader:
            for route, trips in trips_by_route.items():
                if row['trip_id'] in trips:
                    stop_ids_by_route[route].add(row['stop_id'])

    return stop_ids_by_route

    # for route, stop_ids in stop_ids_by_route.items():
    #     print(f"Route {route} has {len(stop_ids)} stops")

def get_shared_stops(routes, stop_ids_by_route):
    """
    Params: routes for which to get shared stops, and the dict of routes as keys and stop_ids as values

    Returns: a set of stop ids (as strings) that are shared across all routes
    """
    shared_stops = set.intersection(*[set_of_stop_ids for route, set_of_stop_ids in stop_ids_by_route.items() if route in routes])
    return shared_stops

def get_stop_coordinates(stop_ids:set) -> dict[str, tuple[float, float]]:
    """
    Params:
    a set of stop ids (as strings) for which to retreive coordinates

    Returns:
    a dict of stop ids (as strings) as keys and tuples of (latitude, longitude), as floats, as values
    """
    stop_coordinates = {}
    with open("transitland_datasets/transitland_wrta_latest/stops.txt",'r') as stops:
        reader = csv.DictReader(stops)
        for row in reader:
            if row['stop_id'] in stop_ids:
                stop_coordinates[row['stop_id']] = (float(row['stop_lat']), float(row['stop_lon']))
    return stop_coordinates

def write_stop_coordinates(all_stop_coordinates: dict[str, tuple[float, float]], filename: str):
    with open(filename, 'w', newline='') as stop_coords:
        writer = csv.writer(stop_coords)
        writer.writerow(['stop_id', 'latitude', 'longitude'])
        for stop_id, (lat, lon) in all_stop_coordinates.items():
            writer.writerow([stop_id, lat, lon])

Corridors = {
    'Orange':["19","27","33"], #note 33 seems to extend wayyyy out of the city
    'Blue':["5","12"], #maybe include 12E?
    'Green':["23","26"]
}

routes_set = set()
for routes in Corridors.values():
    for route in routes:
        routes_set.add(route)

stop_ids_by_route = get_stop_ids_by_routes(routes_set)

# get all stop ids across all routes, rather than by route

"""
all_stop_ids = set()

for stop_ids_sets in stop_ids_by_route.values():
    all_stop_ids.update(stop_ids_sets)

all_stop_coordinates = get_stop_coordinates(all_stop_ids)

write_stop_coordinates(all_stop_coordinates, "all_stops_on_HF_corridors.csv")
"""

stop_ids_by_corridor = {}
for corridor, routes in Corridors.items():
    stop_ids_by_corridor[corridor] = get_shared_stops(routes, stop_ids_by_route)

ids_and_coords_by_corridor = {}
for corridor, stop_ids in stop_ids_by_corridor.items():
    ids_and_coords_by_corridor[corridor] = get_stop_coordinates(stop_ids)

for corridor, ids_and_coords in ids_and_coords_by_corridor.items():
    write_stop_coordinates(ids_and_coords, f"{corridor}_corridor_shared_stops.csv")
        



