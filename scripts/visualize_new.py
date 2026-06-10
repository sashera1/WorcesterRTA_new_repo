
import csv
import folium

def create_corridor_visualization():
    # --- Configuration ---
    points_dir = "data/processed/stops_organized_data"
    raw_dir = "data/raw/transitland_wrta_latest"

    points_to_visualize = {
        'Orange': f"{points_dir}/Orange_corridor_shared_stops.csv",
        'Blue': f"{points_dir}/Blue_corridor_shared_stops.csv",
        'Green': f"{points_dir}/Green_corridor_shared_stops.csv"
    }

    trips_full_coverage = {
        'Orange':["0_1328542", "0_1328536"], 
        'Blue':["2_7328185", "1_6327651"], 
        'Green':["1_6327887", "1_6327879"]
    }

    trips_txt_path = f"{raw_dir}/trips.txt"
    shapes_txt_path = f"{raw_dir}/shapes.txt"
    stops_txt_path = f"{raw_dir}/stops.txt" # Needed to look up exact lat/lon of stops

    # --- Step 1: Map trips to shape_ids and colors ---
    # Example: shape_to_color['shape_123'] = 'Orange'
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

    # --- Step 2: Extract shape line coordinates ---
    # Extract only the points for shapes we care about
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

    # Sort each shape's points by sequence to ensure the line draws correctly
    for s_id in shape_points:
        shape_points[s_id].sort(key=lambda x: x[0])

    # --- Step 3: Load all Stop Coordinates ---
    stop_lookup = {}
    with open(stops_txt_path, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            stop_lookup[row['stop_id']] = (float(row['stop_lat']), float(row['stop_lon']))

    # --- Step 4: Build the Map ---
    # Start with a blank map (we will auto-center it later)
    m = folium.Map(tiles="CartoDB positron")

    # Variables to track the bounding box of ONLY the stops
    min_lat, max_lat = float('inf'), float('-inf')
    min_lon, max_lon = float('inf'), float('-inf')

    # A. Plot the Stops (and calculate bounds)
    for color, path in points_to_visualize.items():
        with open(path, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                s_id = row['stop_id']
                if s_id in stop_lookup:
                    lat, lon = stop_lookup[s_id]
                    
                    # Update the bounding box
                    min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
                    min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)

                    # Draw the stop as a circle
                    folium.CircleMarker(
                        location=(lat, lon),
                        radius=5, # Size of the dot
                        color=color.lower(), # Outline color
                        fill=True,
                        fill_color=color.lower(),
                        fill_opacity=1.0,
                        tooltip=f"Stop: {s_id}" # Hover text
                    ).add_to(m)

    # B. Plot the Route Shapes (Lines)
    for s_id, pts in shape_points.items():
        # Drop the sequence number, keep only (lat, lon) for Folium
        line_coords = [(lat, lon) for seq, lat, lon in pts]
        route_color = shape_to_color[s_id].lower()
        
        folium.PolyLine(
            locations=line_coords,
            color=route_color,
            weight=4, # Thickness of the line
            opacity=0.6, # Slightly transparent so it doesn't hide the stops
            tooltip=f"Shape: {s_id}"
        ).add_to(m)

    # --- Step 5: Fit Bounds and Save ---
    # This forces the map window to crop exactly to the edges of your stops
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    output_file = "worcester_corridors_map.html"
    m.save(output_file)
    print(f"Visualization saved successfully to {output_file}!")

# Run the function
create_corridor_visualization()




