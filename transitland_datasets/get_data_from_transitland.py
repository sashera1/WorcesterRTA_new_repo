import csv

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
Corridors = {
    'Orange':[19,27,33], #note 33 seems to extend wayyyy out of the city
    'Blue':[5,12], #maybe include 12E?
    'Green':[23,26]
}
trips_by_route = {}
for corridor, routes in Corridors.items():
    for route in routes:
        trips_by_route[str(route)] = []


with open("transitland_datasets/transitland_wrta_latest/routes.txt",'r') as routes:
    reader = csv.DictReader(routes)
    for row in reader:
        if row['route_id'] in trips_by_route.keys():
            trips_by_route[row['route_id']].append(row)
            print(row)