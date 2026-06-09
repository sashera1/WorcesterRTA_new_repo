import matplotlib.pyplot as plt
import csv
import json
from src.toolkits.geometric_toolset import pad_boundry
from src.config import debug_mode

#TODO LATER: refactor to visualize stops by corridor/route and polygons in general,
#and to be flexible about number of each kind of param
#and for label to be related to which things are being visualized, 
#and appropriate details, ie, if for area around corridor,
#label includes distance from stops, etc

def visualize_points(color, points_path, order=3):
    lats = []
    longs = []
    
    # Read the CSV using the built-in csv module
    with open(points_path, mode='r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            try:
                # Extract coordinates and ignore stop_id
                lats.append(float(row['latitude']))
                longs.append(float(row['longitude']))
            except (ValueError, KeyError):
                # Skip rows that are missing latitude/longitude or have invalid data
                if debug_mode:
                    print(f"skipped row while loading points for visualization")
                continue
    
    if lats and longs:
        # Plot Longitude (X) and Latitude (Y)
        # Use the dictionary key as the color, converted to lowercase just in case
        plt.scatter(longs, 
                    lats, 
                    c=color.lower(), 
                    label=f"{color} Corridor", 
                    s=20, 
                    alpha=0.5,
                    zorder=order)

def visualize_polygon(polygon, order=2):
    try:
        polygon_path = polygon["path"] 
        polygon_label = polygon["label"] if "label" in polygon else None
        polygon_color = polygon["color"] if "color" in polygon else 'grey' 
        linestyle = polygon["linestyle"] if "linestyle" in polygon else 'solid'

        with open(polygon_path, 'r', encoding='utf-8') as f:
            polygon_json = json.load(f)
        # GeoJSON Polygons store coordinates in an array where the 0th element is the exterior ring
        coordinates = polygon_json["features"][0]["geometry"]["coordinates"][0]
        
        # Separate into X (longitude) and Y (latitude)
        polygon_longitudes = [coord[0] for coord in coordinates]
        polygon_latitudes = [coord[1] for coord in coordinates]
        
        plt.plot(polygon_longitudes, 
                 polygon_latitudes, 
                 color=polygon_color, 
                 linewidth=1, 
                 label=polygon_label,
                 linestyle=linestyle,
                 zorder=order)
        
    except (KeyError, IndexError) as e:
        print(f"Error extracting boundary coordinates: {e}")

def visualize(csv_paths_by_color: dict | None = None, 
              main_polygons: list[dict] | None = None,
              background_polygons: list[dict] | None = None):
    
    plt.figure(figsize=(10, 8))

    if csv_paths_by_color:
        for color_name, file_path in csv_paths_by_color.items():
            visualize_points(color_name, file_path, order=3)

    if main_polygons:
        for polygon in main_polygons:
            visualize_polygon(polygon, order=2)

    #explicitly force dimensions
    xlim = plt.xlim()
    ylim = plt.ylim()

    xlim,ylim=pad_boundry(xlim,ylim,0.10)

    if background_polygons:
        for polygon in background_polygons:
            visualize_polygon(polygon, order=1)

    plt.xlim(xlim)
    plt.ylim(ylim)

    #added for better visualization
    # degree projection will have visual warp
    #adjusted for worcester,
    #hardcoded but if i *really* want this code to be flexible (for other places)
    #can be refactored (put in toolkit)
    aspect_ratio_adjustment_worcester = 1.35

    
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Transit Stop Coordinates")
    
    plt.gca().set_aspect(aspect_ratio_adjustment_worcester)
    
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.show()

points_dir = "data/processed/stops_organized_data"

points_to_visualize = {
    'Orange': f"{points_dir}/Orange_corridor_shared_stops.csv",
    'Blue': f"{points_dir}/Blue_corridor_shared_stops.csv",
    'Green': f"{points_dir}/Green_corridor_shared_stops.csv"
}

points_to_visualize_consolidated = {
    'Orange': f"{points_dir}/Orange_corridor_shared_stops_consolidated.csv",
    'Blue': f"{points_dir}/Blue_corridor_shared_stops_consolidated.csv",
    'Green': f"{points_dir}/Green_corridor_shared_stops_consolidated.csv"
}

corridor_buffer_poly = {
    "path":"data/processed/area_around_stops/three_corridor_polygon_radius_400.geojson",
    "label":"400m radius around HF corridor stops",
    "color":"red"
}

worcester_boundary = {
    "path":"data/raw/worcester_municipal_boundary.geojson",
    "label":"Worcester Municipal Boundary",
    "color":"red",
    "linestyle":"dashed"
}

# visualize(
#     points_to_visualize,
#     [corridor_buffer_poly],
#     [worcester_boundary])

visualize(
    points_to_visualize_consolidated,
    [corridor_buffer_poly],
    [worcester_boundary])


