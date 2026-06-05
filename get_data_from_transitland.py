from toolkits.data_ingestion import get_stop_ids_by_routes, get_shared_stops, get_stop_coordinates, write_stop_coordinates
import pathlib
#TO RUN
#python -m transitland_datasets.get_data_from_transitland
#-m is necessary for imports 
#to treat project as a module
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

if __name__=='__main__':

    dest_dir_stops_by_corridor = pathlib.Path("stops_organized_data")
    dest_dir_stops_by_corridor.mkdir(exist_ok=True)

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

    stop_ids_by_corridor = {}
    for corridor, routes in Corridors.items():
        stop_ids_by_corridor[corridor] = get_shared_stops(routes, stop_ids_by_route)

    #get all stops on any corridor
    #there is repeat code here and when getting coords for each corridor
    #i will refactor later

    all_stop_ids = set()

    for stop_ids_sets in stop_ids_by_corridor.values():
        all_stop_ids.update(stop_ids_sets)

    all_stop_coordinates = get_stop_coordinates(all_stop_ids)

    write_stop_coordinates(all_stop_coordinates, "stops_organized_data/all_stops_on_HF_corridors.csv")


    ids_and_coords_by_corridor = {}
    for corridor, stop_ids in stop_ids_by_corridor.items():
        ids_and_coords_by_corridor[corridor] = get_stop_coordinates(stop_ids)

    for corridor, ids_and_coords in ids_and_coords_by_corridor.items():
        write_stop_coordinates(ids_and_coords, f"stops_organized_data/{corridor}_corridor_shared_stops.csv")
            



