from src.config import debug_mode
import csv

"""
TODO at some point, if accessing the same raw data over and over again:
change architecture to an instance based approach
a set of gtfs data (like transitland_wrta_latest)
is loaded by instantiating an object,
and then, each time a .txt file is used,
cache it

in the meantime, explicit arguments will work for file dest
"""

def get_stop_ids_by_routes(
    routes : set|list, 
    directory:str, 
    trips_filename:str = "trips.txt", 
    stop_times_filename:str = "stop_times.txt") -> dict[str, set[str]]:
    """
    Params: 
    a set or list of route numbers (as strings or integers), specifying the routes from which to retreive stop ids

    Returns:
    a dict of route numbers (as strings) as keys and sets of stop ids (as strings) as values
    """
    trips_by_route = {}
    for route in routes:
        trips_by_route[route] = []
    
    with open(f"{directory}/{trips_filename}",'r') as trips:
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
    with open(f"{directory}/{stop_times_filename}",'r') as stop_times:
        reader = csv.DictReader(stop_times)
        for row in reader:
            for route, trips in trips_by_route.items():
                if row['trip_id'] in trips:
                    stop_ids_by_route[route].add(row['stop_id'])

    if debug_mode:
        for route, stop_ids in stop_ids_by_route.items():
            print(f"Route {route} has {len(stop_ids)} stops")

    return stop_ids_by_route


def get_shared_stops(routes, stop_ids_by_route) -> set[str]:
    """
    Params: routes for which to get shared stops, and the dict of routes as keys and stop_ids as values

    Returns: a set of stop ids (as strings) that are shared across all routes
    """
    shared_stops = set.intersection(*[set_of_stop_ids for route, set_of_stop_ids in stop_ids_by_route.items() if route in routes])
    return shared_stops

def get_stop_coordinates(stop_ids:set, directory: str, stops_filename:str = "stops.txt") -> dict[str, tuple[float, float]]:   
    """
    Params:
    a set of stop ids (as strings) for which to retreive coordinates

    Returns:
    a dict of stop ids (as strings) as keys and tuples of (latitude, longitude), as floats, as values
    """
    stop_coordinates = {}
    with open(f"{directory}/{stops_filename}",'r') as stops:
        reader = csv.DictReader(stops)
        for row in reader:
            if row['stop_id'] in stop_ids:
                stop_coordinates[row['stop_id']] = (float(row['stop_lat']), float(row['stop_lon']))
    return stop_coordinates

def write_stop_coordinates(all_stop_coordinates: dict[str, tuple[float, float]], directory:str,filename: str):
    """
    Params:
    a dictionary of stop ids (as strings) as keys and tuples of (latitude, longitude), as floats, as values.
    and a file path to which the coordinates are to be written

    Returns:
    nothing (but writes to the file path)
    """
    with open(f"{directory}/{filename}", 'w', newline='') as stop_coords:
        writer = csv.writer(stop_coords)
        writer.writerow(['stop_id', 'latitude', 'longitude'])
        for stop_id, (lat, lon) in all_stop_coordinates.items():
            writer.writerow([stop_id, lat, lon])



