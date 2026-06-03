#NOTE transparency: this script was partially coded with AI
import matplotlib.pyplot as plt
import csv
import json


#TODO refactor to visualize stops by corridor/route and polygons in general,
#and to be flexible about number of each kind of param
#and for label to be related to which things are being visualized, 
#and appropriate details, ie, if for area around corridor,
#label includes distance from stops, etc

#also for refactoring: separate(have to be in order cuz can freeze and unfreeze) set of polygon args
#for main (effects zoom) and secondary (doesn't effect zoom) polygons

def visualize(csv_paths_by_color:dict, *polygons):
    plt.figure(figsize=(10, 8))
    points_plotted = False

    for polygon in polygons:
        try:
            polygon_path = polygon[0] 
            polygon_label = polygon[1] if len(polygon) > 1 else None
            polygon_color = polygon[2] if len(polygon) > 2 else 'grey' 
            linestyle = polygon[3] if len(polygon) > 3 else 'solid'

            with open(polygon_path, 'r', encoding='utf-8') as f:
                boundary_json = json.load(f)
            # GeoJSON Polygons store coordinates in an array where the 0th element is the exterior ring
            coordinates = boundary_json["features"][0]["geometry"]["coordinates"][0]
            
            # Separate into X (longitude) and Y (latitude)
            boundary_longs = [coord[0] for coord in coordinates]
            boundary_lats = [coord[1] for coord in coordinates]
            
            plt.plot(boundary_longs, boundary_lats, color=polygon_color, linewidth=1, label=polygon_label,linestyle=linestyle)
            points_plotted = True
        except (KeyError, IndexError) as e:
            print(f"Error extracting boundary coordinates: {e}")

    for color_name, file_path in csv_paths_by_color.items():
            
        lats = []
        lons = []
        
        # Read the CSV using the built-in csv module
        with open(file_path, mode='r', encoding='utf-8') as csvfile:
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
            plt.scatter(lons, lats, c=color_name.lower(), label=f"{color_name} Corridor", s=20, alpha=0.8)
            points_plotted = True

    #added for better visualization
    # degree projection will have visual warp
    #adjusted for worcester,
    #hardcoded but can be refactored if i *really* want this code to be flexible (for other places)
    aspect_ratio_adjustment_worcester = 1.35

    if points_plotted:
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.title("Transit Stop Coordinates")
        
        # Set aspect ratio to 'equal' so the map doesn't stretch geographically
        plt.gca().set_aspect(aspect_ratio_adjustment_worcester, adjustable='datalim')
        
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.legend()
        
        # Display the plot in a window
        plt.show()


to_visualize = {
    'Orange': "stops_organized_data/Orange_corridor_shared_stops.csv",
    'Blue': "stops_organized_data/Blue_corridor_shared_stops.csv",
    'Green': "stops_organized_data/Green_corridor_shared_stops.csv"
}

#visualize(to_visualize, "worcester_municipal_boundary.geojson",Worcester Municipal Boundary")

#visualize({'Red':"stops_organized_data/all_stops_on_HF_corridors.csv"}, "worcester_municipal_boundary.geojson")

visualize(
    to_visualize,
    ("all_stops_polygon_radius_500.geojson","500m radius around HF corridor stops","red"),
    ("worcester_municipal_boundary.geojson","Worcester Municipal Boundary","red","dashed"))

# visualize(
#     to_visualize,
#     ("all_stops_polygon_radius_500.geojson","500m radius around HF corridor stops","red"))


