from src.toolkits.data_ingestion import get_stop_ids_by_routes, get_shared_stops, get_stop_coordinates, write_stop_coordinates
"""
the point of this script is to get all stops by each route


TO RUN:
python -m scripts.get_data_from_transitland

-m is necessary for imports 
to treat project as a module
and their coordinates
"""

if __name__=='__main__':

    src_dir = "data/raw/transitland_wrta_latest"
    dest_dir = "data/processed/stops_organized_data"

    corridors = {
        'Orange':["19","27","33"], #note 33 seems to extend wayyyy out of the city
        'Blue':["5","12"], #maybe include 12E?
        'Green':["23","26"]
    }

    routes_set = set()
    for routes in corridors.values():
        for route in routes:
            routes_set.add(route)

    stop_ids_by_route = get_stop_ids_by_routes(routes_set, src_dir)

    stop_ids_by_corridor = {}
    for corridor, routes in corridors.items():
        stop_ids_by_corridor[corridor] = get_shared_stops(routes, stop_ids_by_route)

    
    all_stop_ids = set()

    for stop_ids_sets in stop_ids_by_corridor.values():
        all_stop_ids.update(stop_ids_sets)

    all_stop_coordinates = get_stop_coordinates(all_stop_ids, src_dir)

    write_stop_coordinates(all_stop_coordinates, dest_dir, "all_stops_on_HF_corridors.csv")

    for corridor, stop_ids in stop_ids_by_corridor.items():
        corridor_stop_coordinates = {
        stop_id: all_stop_coordinates[stop_id]
        for stop_id in stop_ids
        }
    
        write_stop_coordinates(corridor_stop_coordinates, dest_dir, f"{corridor}_corridor_shared_stops.csv")
    
            



