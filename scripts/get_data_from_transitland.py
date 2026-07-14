from src.toolkits.data_ingestion import get_stop_ids_by_routes, get_shared_stops, get_stop_coordinates, write_stop_coordinates
from src.toolkits.geometric_toolset import consolidate_stops
from src.config import debug_mode, corridors
import csv
from pathlib import Path
import itertools
"""
the point of this script is to get all stops by each route


TO RUN:
python -m scripts.get_data_from_transitland

-m is necessary for imports 
to treat project as a module
and their coordinates
"""

def get_data():
    src_dir = "data/raw/gtfs_data_2025/version_1"
    dest_dir = "data/processed/stops_organized_data_2025"


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
    
def consolidate_data_naive(src_dir, dest_dir):

    
    stop_ids = []
    coords = []
    to_ignore_stops_in_loop = ["0_3130","0_3530"] #TODO add stops in central loop

    with open(f"{src_dir}/all_stops_on_HF_corridors.csv",'r') as unconsolidated: #someday refactor as a load func 
            reader = csv.DictReader(unconsolidated)
            for row in reader:
                stop_ids.append(row["stop_id"])
                coords.append((float(row["latitude"]),float(row["longitude"])))

    #takes like 3 minutes
    consolidated_data = consolidate_stops(stop_ids,coords,to_ignore_stops_in_loop, threshold_meters=100,consolidation_limit=2)

    with open(f"{dest_dir}/all_stops_on_HF_corridors_consolidated.csv",'w', newline='') as consolidated:
        writer = csv.writer(consolidated)
        writer.writerow(['stop_id', 'latitude', 'longitude'])
        for stop_id, (lat, lon) in consolidated_data.items():
            writer.writerow([";".join(stop_id), lat, lon])

    for corridor in ["Blue", "Green", "Orange"]:
        stops_for_corridor = []

        with open(f"{src_dir}/{corridor}_corridor_shared_stops.csv","r") as unconsolidated_corridor:
            reader = csv.DictReader(unconsolidated_corridor)
            for row in reader:
                stops_for_corridor.append(row["stop_id"])

        with open(f"{dest_dir}/{corridor}_corridor_shared_stops_consolidated.csv",'w', newline='') as consolidated_corridor:
            writer = csv.writer(consolidated_corridor)
            writer.writerow(['stop_id', 'latitude', 'longitude'])
            for id_tuple, (lat, long) in consolidated_data.items():
                
                for stop in stops_for_corridor:
                    if stop in id_tuple:
                        writer.writerow([";".join(id_tuple), lat, long])
                        break

    """maybe would be refactored (do before writing csvs as is done in get_data()
    but we already have that data so is just writted off of what we already have)"""


def child_to_parent_stops(
    stops_txt_path: str | Path,
    corridor_dir_path: str | Path,
    corridor_files: dict[str, str],
    output_csv_dir: str | Path
    ):
    stops_txt_path = Path(stops_txt_path)
    corridor_dir_path = Path(corridor_dir_path)
    output_csv_dir = Path(output_csv_dir)

    starting_sets = {color: set() for color in corridor_files}

    for color, filename in corridor_files.items():
        filepath = corridor_dir_path / filename  
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                starting_sets[color].add(row['stop_id'])

    result_sets = {color: set() for color in corridor_files}
    result_dicts = {color: {} for color in corridor_files}

    with open(stops_txt_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            stop_id = row['stop_id']

            if stop_id.startswith('1'):
                reader = itertools.chain([row], reader)
                break

            parent_id = row.get('parent_station', '').strip()

            for color, start_set in starting_sets.items():
                if stop_id in start_set and parent_id:
                    result_sets[color].add(parent_id)

        if debug_mode: print("first loop over, second loop starting")

        for row in reader:
            stop_id = row['stop_id']
            lat = float(row['stop_lat'])
            lon = float(row['stop_lon'])

            for color, res_set in result_sets.items():
                if stop_id in res_set:
                    result_dicts[color][stop_id] = (lat, lon)

        if debug_mode: print("second loop over")

    output_csv_dir.mkdir(parents=True, exist_ok=True) 

    for color, final_dict in result_dicts.items():
        out_filename = f"{color}_corridor_shared_stops_parent.csv"
        out_filepath = output_csv_dir / out_filename  

        with open(out_filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['stop_id', 'stop_lat', 'stop_lon'])
            
            for s_id, (lat, lon) in final_dict.items():
                writer.writerow([s_id, lat, lon])

    if debug_mode: print(f"Successfully processed and generated consolidated CSVs for {len(corridor_files)} corridors.")



            
if __name__=='__main__':
    #get_data()


    unconsolidated_dir="data/processed/stops_organized_data"
    files_to_consolidate = {
    'Orange': "Orange_corridor_shared_stops.csv",
    'Blue': "Blue_corridor_shared_stops.csv",
    'Green': "Green_corridor_shared_stops.csv"
    }

    # consolidate_corridor_stops("data/raw/gtfs_data_2026/stops.txt",
    #                            unconsolidated_dir,
    #                            files_to_consolidate,
    #                            "data/processed/stops_consolidated_data")

    #barely a reduction - maybe check if parent stops are at all routes per corridor?

    consolidate_data_naive("data/processed/stops_organized_data_2025","data/processed/stops_consolidated_data_2025")
    
                


    
    


