import json

def add_external_region(path):
    #TODO it seems the tomtom data is still including trips that started or ended
    #outside the regions, despite the settings i put
    #thus this adds to the existing tiered json
    #a buffer donut to absorb everything
    #maybe do here, maybe add to the generater func itself
    pass

def add_name_property_to_geojson(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        
        stop_id = props.get("stop_id", "unknown")
        tier = props.get("tier", "unknown")
        
       
        new_name = f"{stop_id}_{tier}"
        
        props["name"] = new_name

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"Successfully processed {len(data.get('features', []))} features.")
    print(f"Saved to: {path}")

# Run the script
add_name_property_to_geojson(
    "data/processed/area_around_stops/tiered_regions_around_stops.geojson"
)