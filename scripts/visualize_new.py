
import csv
import folium

def create_corridor_visualization():
    # --- Configuration ---
    points_dir = "data/processed/stops_organized_data"
    dir_consol = "data/processed/stops_consolidated_data"
    raw_dir = "data/raw/transitland_wrta_latest"

    # points_to_visualize = {
    #     'Orange': f"{points_dir}/Orange_corridor_shared_stops.csv",
    #     'Blue': f"{points_dir}/Blue_corridor_shared_stops.csv",
    #     'Green': f"{points_dir}/Green_corridor_shared_stops.csv"
    # }
    points_to_visualize = {
    'Orange': f"{dir_consol}/Orange_corridor_shared_stops_consolidated.csv",
    'Blue': f"{dir_consol}/Blue_corridor_shared_stops_consolidated.csv",
    'Green': f"{dir_consol}/Green_corridor_shared_stops_consolidated.csv"
}

    trips_full_coverage = {
        'Orange':["0_1328542", "0_1328536"], 
        'Blue':["2_7328185", "1_6327651"], 
        'Green':["1_6327887", "1_6327879"]
    }

    trips_txt_path = f"{raw_dir}/trips.txt"
    shapes_txt_path = f"{raw_dir}/shapes.txt"
    stops_txt_path = f"{raw_dir}/stops.txt" 

    trip_to_color = {}
    for color, trips in trips_full_coverage.items():
        for t in trips:
            trip_to_color[t] = color

    shape_to_color = {}
    with open(trips_txt_path, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            t_id = row['trip_id']
            if t_id in trip_to_color:
                shape_to_color[row['shape_id']] = trip_to_color[t_id]

    shape_points = {s_id: [] for s_id in shape_to_color}
    with open(shapes_txt_path, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            s_id = row['shape_id']
            if s_id in shape_points:
                shape_points[s_id].append((
                    int(row['shape_pt_sequence']),
                    float(row['shape_pt_lat']),
                    float(row['shape_pt_lon'])
                ))

    for s_id in shape_points:
        shape_points[s_id].sort(key=lambda x: x[0])

    stop_lookup = {}
    with open(stops_txt_path, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            stop_lookup[row['stop_id']] = (float(row['stop_lat']), float(row['stop_lon']))

    
    m = folium.Map(tiles="CartoDB positron")

    min_lat, max_lat = float('inf'), float('-inf')
    min_lon, max_lon = float('inf'), float('-inf')

    for color, path in points_to_visualize.items():
        with open(path, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                s_id = row['stop_id']
                #for visualizing consolidated
                s_id = s_id.split(";")[0]
                
                if s_id in stop_lookup:
                    lat, lon = stop_lookup[s_id]
                    
                    min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
                    min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)

                    folium.CircleMarker(
                        location=(lat, lon),
                        radius=5, 
                        color=color.lower(),
                        fill=True,
                        fill_color=color.lower(),
                        fill_opacity=1.0,
                        tooltip=f"Stop: {s_id}"
                    ).add_to(m)

    for s_id, pts in shape_points.items():
        line_coords = [(lat, lon) for seq, lat, lon in pts]
        route_color = shape_to_color[s_id].lower()
        
        folium.PolyLine(
            locations=line_coords,
            color=route_color,
            weight=4,
            opacity=0.6, 
            tooltip=f"Shape: {s_id}"
        ).add_to(m)

    
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    output_file = "worcester_corridors_map.html"
    m.save(output_file)
    print(f"Visualization saved successfully to {output_file}!")

create_corridor_visualization()




