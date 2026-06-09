from src.toolkits.data_ingestion import get_stop_ids_by_routes, get_shared_stops, get_stop_coordinates, write_stop_coordinates
from src.toolkits.geometric_toolset import consolidate_stops
import csv
"""
the point of this script is to get all stops by each route


TO RUN:
python -m scripts.get_data_from_transitland

-m is necessary for imports 
to treat project as a module
and their coordinates
"""

def get_data():
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
    

    
            
if __name__=='__main__':
    #get_data()

    #so messy! lots of repeat! will refactor when not on deadline
    #also, if getting more data, refactor so this goes with the flow of having data in memory,
    #right now some data is read from csv's

    directory = "data/processed/stops_organized_data"
    stop_ids = []
    coords = []

    with open(f"{directory}/all_stops_on_HF_corridors.csv",'r') as unconsolidated: #someday refactor as a load func 
            reader = csv.DictReader(unconsolidated)
            for row in reader:
                stop_ids.append(row["stop_id"])
                coords.append((float(row["latitude"]),float(row["longitude"])))

    #takes like 3 minutes
    consolidated_data = consolidate_stops(stop_ids,coords,threshold_meters=50,consolidation_limit=2)

    with open(f"{directory}/all_stops_on_HF_corridors_consolidated.csv",'w', newline='') as consolidated:
        writer = csv.writer(consolidated)
        writer.writerow(['stop_id(s)', 'latitude', 'longitude'])
        for stop_id, (lat, lon) in consolidated_data.items():
            writer.writerow([";".join(stop_id), lat, lon])

    for corridor in ["Blue", "Green", "Orange"]:
        stops_for_corridor = []

        with open(f"{directory}/{corridor}_corridor_shared_stops.csv","r") as unconsolidated_corridor:
            reader = csv.DictReader(unconsolidated_corridor)
            for row in reader:
                stops_for_corridor.append(row["stop_id"])

        with open(f"{directory}/{corridor}_corridor_shared_stops_consolidated.csv",'w', newline='') as consolidated_corridor:
            writer = csv.writer(consolidated_corridor)
            writer.writerow(['stop_id(s)', 'latitude', 'longitude'])
            for id_tuple, (lat, long) in consolidated_data.items():
                
                for stop in stops_for_corridor:
                    if stop in id_tuple:
                        writer.writerow([";".join(id_tuple), lat, long])
                        break
                


    
    


