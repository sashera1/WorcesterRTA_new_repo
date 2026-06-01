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

def get_stop_ids_by_routes(routes:set) -> dict[str, set[str]]:
    trips_by_route = {}
    for route in routes:
        trips_by_route[str(route)] = []
    
    with open("transitland_datasets/transitland_wrta_latest/trips.txt",'r') as trips:
        reader = csv.DictReader(trips)
        for row in reader:
            if row['route_id'] in trips_by_route.keys():
                trips_by_route[row['route_id']].append(row['trip_id'])

    stop_ids_by_route = {}
    for route in routes:
        stop_ids_by_route[str(route)] = set()

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

Corridors = {
    'Orange':[19,27,33], #note 33 seems to extend wayyyy out of the city
    'Blue':[5,12], #maybe include 12E?
    'Green':[23,26]
}

routes_set = set()
for routes in Corridors.values():
    for route in routes:
        routes_set.add(str(route))

stop_ids_by_route = get_stop_ids_by_routes(routes_set)

for stop_id in stop_ids_by_route['19']:
    print(stop_id)




