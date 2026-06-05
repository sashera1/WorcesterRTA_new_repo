"""
DESC:
takes coords from csv (format: stop_id, lat, lon) and creates a polygon 
encompassing the union of (an approximation of) circles of a certain radius around each stop
output should be a geojson such that can be useds for tomtom

NOTE:
1) input is lat,long but geojson needs to be long, lat
2) these are as degrees: must be converted to non-degree system for distance calc
and then back
"""
import csv
import json
from shapely.geometry import Point, mapping
from shapely.ops import transform, unary_union
from pyproj import CRS, Transformer
from toolkits import geometric_toolset #TODO refactor some stuff from this file into here

def generate_geojson_polygon(input_file:str,output_polygon_file:str, radius_meters: float):
    
    input_data = []
    with open(input_file, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Check for valid lat/lon to avoid breaking on malformed rows
            if row.get('latitude') and row.get('longitude'):
                input_data.append(
                    [float(row["latitude"]),
                     float(row["longitude"])]
                )


    #arbitrary selection of centering data for projection to non-degree system for distance calc
    #maybe use the transfer station in the middle of city but
    #really doesnt matter
    #just that would feel better
    center_lat = input_data[0][0]
    center_lon = input_data[0][1]

    degree_projection = CRS(proj="aeqd", lat_0=center_lat, lon_0=center_lon, datum="WGS84")
    WGS_84_projection = CRS("EPSG:4326")

    
    project_from_deg_to_meters = Transformer.from_crs(WGS_84_projection, degree_projection, always_xy=True).transform
    project_from_meters_to_degrees = Transformer.from_crs(degree_projection, WGS_84_projection, always_xy=True).transform

    circles = []
    for item in input_data:
        # note lat, long are swapped! geojson format does it different from gtfs format
        p_degrees = Point(item[1], item[0])
        
        #transform to meters, draw the circle, and transform back to degrees
        p_meters = transform(project_from_deg_to_meters, p_degrees)
        circle_meters = p_meters.buffer(radius_meters, quad_segs=16)
        circle_degrees = transform(project_from_meters_to_degrees, circle_meters)
        
        circles.append(circle_degrees)

        unioned_geometry = unary_union(circles)

    geojson_dict = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                # mapping converts a shapely object into geojson
                "geometry": mapping(unioned_geometry) 
            }
        ]
    }

    with open(output_polygon_file, mode='w', encoding='utf-8') as f:
        json.dump(geojson_dict, f, indent=2)
    
radius_meters = 500
generate_geojson_polygon("stops_organized_data/all_stops_on_HF_corridors.csv", f"all_stops_polygon_radius_{radius_meters}.geojson", radius_meters=radius_meters)