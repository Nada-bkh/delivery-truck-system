import json
import requests

# Constants
TRUCKS_JSON_URL = "http://backend:3000/api/trucks"
OSRM_URL = "http://osrm:5000/route/v1/truck"
CO2_PER_TON_KM = 0.115
DEFAULT_SPEED = 70 
SPEED_OPTIONS = [60, 70, 80]

def fetch_trucks():
    try:
        response = requests.get(TRUCKS_JSON_URL)
        return response.json()
    except Exception as e:
        print("Error fetching truck data:", e)
        return []

def fetch_route_distance(coords):
    coord_str = ";".join([f"{c['lon']},{c['lat']}" for c in coords])
    url = f"{OSRM_URL}/{coord_str}?overview=false"
    try:
        res = requests.get(url)
        data = res.json()
        if "routes" in data and data["routes"]:
            return data["routes"][0]["distance"] / 1000 
    except:
        return None
    return None

def calculate_emission(weight_tons, distance_km, speed_kmh):
    base_emission = distance_km * weight_tons * CO2_PER_TON_KM
    speed_factor = 1 + (speed_kmh - DEFAULT_SPEED) * 0.01
    return base_emission * speed_factor

def optimize_truck_routes():
    trucks = fetch_trucks()
    optimized = []

    for truck in trucks:
        coords = truck.get("route", [])
        weight_tons = truck.get("weight", 10000) / 1000
        distance_km = fetch_route_distance(coords)
        if not distance_km:
            continue

        emissions_by_speed = {}
        for speed in SPEED_OPTIONS:
            emissions_by_speed[speed] = calculate_emission(weight_tons, distance_km, speed)

        best_speed = min(emissions_by_speed, key=emissions_by_speed.get)
        optimized.append({
            "truck_id": truck["id"],
            "distance_km": distance_km,
            "weight_tons": weight_tons,
            "best_speed_kmh": best_speed,
            "emissions_kg": round(emissions_by_speed[best_speed], 2)
        })

    return optimized

if __name__ == "__main__":
    results = optimize_truck_routes()
    for r in results:
        print(f"Truck {r['truck_id']}: best speed {r['best_speed_kmh']} km/h, "
              f"distance {r['distance_km']} km, "
              f"CO2: {r['emissions_kg']} kg")
