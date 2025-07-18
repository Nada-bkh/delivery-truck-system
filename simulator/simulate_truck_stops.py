import json
import time
from kafka import KafkaConsumer, KafkaProducer
from math import radians, cos, sin, asin, sqrt

KAFKA_BROKER = 'kafka:9092'
TRUCK_DATA_TOPIC = 'truck-data'
TRUCK_STOPS_TOPIC = 'truck-stops'

MAX_DRIVING_SECONDS = 4.5 * 3600
PAUSE_SECONDS = 45 * 60

producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BROKER],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

consumer = KafkaConsumer(
    TRUCK_DATA_TOPIC,
    bootstrap_servers=[KAFKA_BROKER],
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    group_id='truck-rest-simulator-group',
    auto_offset_reset='latest'
)

driving_time = {}
is_stopped = {}

def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1; dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    c = 2*asin(sqrt(a))
    return 6371000 * c

def find_rest_stop(route):
    """
    Simple heuristic: select a waypoint around halfway in the route as rest stop.
    A better way is to use real rest areas from OSRM or map data.
    """
    if not route or len(route) < 2:
        return None

    mid_index = len(route) // 2
    waypoint = route[mid_index]

    lat = waypoint.get('latitude') or waypoint.get('lat')
    lon = waypoint.get('longitude') or waypoint.get('lng')
    if lat is None or lon is None:
        return None

    return {
        'name': f"Rest Stop near waypoint {mid_index}",
        'coords': [lon, lat]
    }

print("Truck rest stop simulator started...")

for message in consumer:
    data = message.value
    truck_id = data.get('truck_id') or data.get('id')
    if not truck_id:
        continue

    if is_stopped.get(truck_id, False):
        continue

    driving_time[truck_id] = driving_time.get(truck_id, 0) + 1

    if driving_time[truck_id] >= MAX_DRIVING_SECONDS:
        route = data.get('route', [])
        rest_stop = find_rest_stop(route)
        if not rest_stop:
            print(f"No rest stop found in route data for truck {truck_id}, skipping stop.")
            continue

        is_stopped[truck_id] = True

        stop_event = {
            "truck_id": truck_id,
            "state": "Stopped",
            "location": rest_stop['coords'],
            "rest_area_name": rest_stop['name'],
            "pause_duration": PAUSE_SECONDS,
            "timestamp": time.time()
        }
        producer.send(TRUCK_STOPS_TOPIC, stop_event)
        print(f"Truck {truck_id} stopping at {rest_stop['name']} for {PAUSE_SECONDS//60} minutes.")

        driving_time[truck_id] = 0

        time.sleep(PAUSE_SECONDS)

        resume_event = {
            "truck_id": truck_id,
            "state": "En route",
            "timestamp": time.time()
        }
        producer.send(TRUCK_STOPS_TOPIC, resume_event)
        print(f"Truck {truck_id} resumed driving.")

        is_stopped[truck_id] = False
