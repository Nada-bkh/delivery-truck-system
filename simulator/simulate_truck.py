import json
import time
import math
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KAFKA_BROKER = 'kafka:9092'
ROUTE_TOPIC = 'truck-route-updates'
UPDATE_TOPIC = 'truck-updates'

def create_kafka_producer(max_retries=30, retry_delay=2):
    for attempt in range(max_retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=[KAFKA_BROKER],
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                request_timeout_ms=15000,
                retries=3
            )
            logger.info("Successfully connected to Kafka broker")
            return producer
        except NoBrokersAvailable:
            logger.warning(f"Attempt {attempt + 1}/{max_retries}: Kafka broker not available, retrying...")
            time.sleep(retry_delay)
    logger.error("Failed to connect to Kafka producer after retries")
    sys.exit(1)

def create_kafka_consumer(max_retries=30, retry_delay=2):
    for attempt in range(max_retries):
        try:
            consumer = KafkaConsumer(
                ROUTE_TOPIC,
                bootstrap_servers=[KAFKA_BROKER],
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                group_id='truck-simulator-group',
                auto_offset_reset='latest',
                request_timeout_ms=15000,
                session_timeout_ms=10000
            )
            logger.info("Successfully connected to Kafka consumer")
            return consumer
        except NoBrokersAvailable:
            logger.warning(f"Attempt {attempt + 1}/{max_retries}: Kafka broker not available, retrying...")
            time.sleep(retry_delay)
    logger.error("Failed to connect to Kafka consumer after retries")
    sys.exit(1)

def haversine(coord1, coord2):
    R = 6371000
    lon1, lat1 = map(math.radians, coord1)
    lon2, lat2 = map(math.radians, coord2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return R * 2 * math.asin(math.sqrt(a))

def interpolate(start, end, speed_kmh):
    dist = haversine(start, end)
    speed_mps = speed_kmh * 1000 / 3600
    steps = max(int(dist / speed_mps), 1)
    for i in range(steps):
        lat = start[1] + (end[1] - start[1]) * (i / steps)
        lon = start[0] + (end[0] - start[0]) * (i / steps)
        yield [lon, lat]
        time.sleep(1)

def simulate_truck(truck_id, route_data, producer):
    route = route_data['route']
    destination = route_data['destination']
    fallback = route_data.get('alternatives', [])
    speed = [50, 90]

    for i in range(len(route) - 1):
        start = [route[i]['longitude'], route[i]['latitude']]
        end = [route[i + 1]['longitude'], route[i + 1]['latitude']]

        for coord in interpolate(start, end, speed):
            message = {
                'id': truck_id,
                'location': coord,
                'speed': speed,
                'state': 'En route',
                'destination': [destination['longitude'], destination['latitude']],
                'timestamp': time.time(),
                'fallbackRoutes': [
                    [ [pt['longitude'], pt['latitude']] for pt in alt['waypoints'] ]
                    for alt in fallback
                ]
            }
            try:
                producer.send(UPDATE_TOPIC, message)
                logger.info(f"{truck_id} → {coord}")
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

    # Final destination update
    try:
        producer.send(UPDATE_TOPIC, {
            'id': truck_id,
            'location': [destination['longitude'], destination['latitude']],
            'speed': 0,
            'state': 'Arrived',
            'destination': [destination['longitude'], destination['latitude']],
            'timestamp': time.time(),
            'fallbackRoutes': [
                [ [pt['longitude'], pt['latitude']] for pt in alt['waypoints'] ]
                for alt in fallback
            ]
        })
        logger.info(f"{truck_id} arrived at destination.")
    except Exception as e:
        logger.error(f"Failed to send arrival message: {e}")

def listen_for_routes():
    producer = create_kafka_producer()
    consumer = create_kafka_consumer()

    logger.info('Listening for route updates...')
    try:
        for msg in consumer:
            data = msg.value
            truck_id = data.get('truck_id')
            if not truck_id or not data.get('route'):
                logger.warning(f"Invalid message: {data}")
                continue
            logger.info(f"Simulating {truck_id}")
            simulate_truck(truck_id, data, producer)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        consumer.close()
        producer.close()

if __name__ == '__main__':
    listen_for_routes()