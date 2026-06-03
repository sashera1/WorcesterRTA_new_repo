#NOTE transparency: this script was mostly coded with AI
import matplotlib.pyplot as plt
import csv
import json

#TODO refactor to visualize stops by corridor/route and polygons in general,
#and to be flexible about number of each kind of param
#and for label to be related to which things are being visualized, 
#and appropriate details, ie, if for area around corridor,
#label includes distance from stops, etc
def visualize(csv_paths_by_color:dict, polygon : str | None = None, polygon_label : str | None = None):
    plt.figure(figsize=(10, 8))
    points_plotted = False

    if polygon:
        try:
            with open(polygon, 'r', encoding='utf-8') as f:
                boundary_json = json.load(f)
            # GeoJSON Polygons store coordinates in an array where the 0th element is the exterior ring
            coordinates = boundary_json["features"][0]["geometry"]["coordinates"][0]
            
            # Separate into X (longitude) and Y (latitude)
            boundary_longs = [coord[0] for coord in coordinates]
            boundary_lats = [coord[1] for coord in coordinates]
            
            # Plot the boundary as a thin red line
            plt.plot(boundary_longs, boundary_lats, color='red', linewidth=1, label=polygon_label)
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
            plt.scatter(lons, lats, c=color_name.lower(), label=f"{color_name} Corridor", s=30, alpha=0.8)
            points_plotted = True

    if points_plotted:
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.title("Transit Stop Coordinates")
        
        # Set aspect ratio to 'equal' so the map doesn't stretch geographically
        plt.gca().set_aspect('equal', adjustable='datalim')
        
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.legend()
        
        # Display the plot in a window
        plt.show()


to_visualize = {
    'Orange': "stops_organized_data/Orange_corridor_shared_stops.csv",
    'Blue': "stops_organized_data/Blue_corridor_shared_stops.csv",
    'Green': "stops_organized_data/Green_corridor_shared_stops.csv"
}

#visualize(to_visualize, "worcester_municipal_boundary.geojson")

#visualize({'Red':"stops_organized_data/all_stops_on_HF_corridors.csv"}, "worcester_municipal_boundary.geojson")

visualize(to_visualize,"all_stops_polygon_radius_500.geojson")


