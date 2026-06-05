import matplotlib.pyplot as plt
import csv
import json

#TODO refactor to visualize stops by corridor/route and polygons in general,
#and to be flexible about number of each kind of param
#and for label to be related to which things are being visualized, 
#and appropriate details, ie, if for area around corridor,
#label includes distance from stops, etc

#also for refactoring: separate set of polygon args
#for main (effects zoom) and secondary (doesn't effect zoom) polygons
#they have to be plotted in order cuz cant freeze and unfreeze
#could order inputs or have flags for each (or something else)
def visualize_points(color, points_path):
    lats = []
    lons = []
    
    # Read the CSV using the built-in csv module
    with open(points_path, mode='r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            try:
                # Extract coordinates and ignore stop_id
                lats.append(float(row['latitude']))
                lons.append(float(row['longitude']))
            except (ValueError, KeyError):
                # Skip rows that are missing latitude/longitude or have invalid data
                continue
    
    if lats and lons:
        # Plot Longitude (X) and Latitude (Y)
        # Use the dictionary key as the color, converted to lowercase just in case
        plt.scatter(lons, lats, c=color.lower(), label=f"{color} Corridor", s=20, alpha=0.8)

def visualize_polygon(polygon):
    try:
        polygon_path = polygon[0] 
        polygon_label = polygon[1] if len(polygon) > 1 else None
        polygon_color = polygon[2] if len(polygon) > 2 else 'grey' 
        linestyle = polygon[3] if len(polygon) > 3 else 'solid'

        with open(polygon_path, 'r', encoding='utf-8') as f:
            polygon_json = json.load(f)
        # GeoJSON Polygons store coordinates in an array where the 0th element is the exterior ring
        coordinates = polygon_json["features"][0]["geometry"]["coordinates"][0]
        
        # Separate into X (longitude) and Y (latitude)
        polygon_longitudes = [coord[0] for coord in coordinates]
        polygon_latitudes = [coord[1] for coord in coordinates]
        
        plt.plot(polygon_longitudes, polygon_latitudes, color=polygon_color, linewidth=1, label=polygon_label,linestyle=linestyle)
    except (KeyError, IndexError) as e:
        print(f"Error extracting boundary coordinates: {e}")

def visualize(csv_paths_by_color:dict|None=None, *polygons):
    plt.figure(figsize=(10, 8))

    for polygon in polygons:
        visualize_polygon(polygon)
        
    for color_name, file_path in csv_paths_by_color.items():
        visualize_points(color_name, file_path)

    #added for better visualization
    # degree projection will have visual warp
    #adjusted for worcester,
    #hardcoded but if i *really* want this code to be flexible (for other places)
    #can be refactored (put in toolkit)
    aspect_ratio_adjustment_worcester = 1.35

    
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Transit Stop Coordinates")
    
    # Set aspect ratio to 'equal' so the map doesn't stretch geographically
    plt.gca().set_aspect(aspect_ratio_adjustment_worcester, adjustable='datalim')
    
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    
    # Display the plot in a window
    plt.show()

points_dir = "data/processed/stops_organized_data"

to_visualize = {
    'Orange': f"{points_dir}/Orange_corridor_shared_stops.csv",
    'Blue': f"{points_dir}/Blue_corridor_shared_stops.csv",
    'Green': f"{points_dir}/Green_corridor_shared_stops.csv"
}

#visualize(to_visualize, "worcester_municipal_boundary.geojson",Worcester Municipal Boundary")

#visualize({'Red':"stops_organized_data/all_stops_on_HF_corridors.csv"}, "worcester_municipal_boundary.geojson")

visualize(
    to_visualize,
    ("data/processed/area_around_stops/three_corridor_polygon_radius_500.geojson","500m radius around HF corridor stops","red"),
    ("data/raw/worcester_municipal_boundary.geojson","Worcester Municipal Boundary","red","dashed"))

# visualize(
#     to_visualize,
#     ("all_stops_polygon_radius_500.geojson","500m radius around HF corridor stops","red"))


