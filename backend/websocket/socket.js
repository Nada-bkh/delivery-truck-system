const { Server } = require('socket.io');
const { runConsumer } = require('../kafka/consumer');
const { Kafka } = require('kafkajs');
const axios = require('axios');

const kafka = new Kafka({
  clientId: 'route-update-producer',
  brokers: [process.env.KAFKA_BROKERS || 'kafka:9092'],
});

const routeProducer = kafka.producer();

const initializeWebSocket = (server) => {
  const io = new Server(server, {
    cors: {
      origin: ['http://localhost:5173', 'http://localhost:3000'],
      methods: ['GET', 'POST'],
    },
  });

  const connectProducer = async (retries = 5) => {
    for (let i = 0; i < retries; i++) {
      try {
        await routeProducer.connect();
        console.log('Route update producer connected to Kafka');
        return;
      } catch (error) {
        console.error(`Producer connection attempt ${i + 1} failed:`, error.message);
        if (i === retries - 1) throw error;
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    }
  };

  connectProducer().catch(console.error);

  io.on('connection', (socket) => {
    console.log('Client connected:', socket.id);

    socket.emit('message', { type: 'connection_established' });

    socket.on('setRoute', async (route) => {
      try {
        const { departure, destination, truck_id } = route;

        console.log('Received setRoute request:', {
          truck_id,
          departure,
          destination
        });

        if (!departure?.longitude || !departure?.latitude || 
            !destination?.longitude || !destination?.latitude ||
            isNaN(departure.longitude) || isNaN(departure.latitude) ||
            isNaN(destination.longitude) || isNaN(destination.latitude)) {
          throw new Error('Invalid route coordinates - must be valid numbers');
        }

        if (!truck_id || typeof truck_id !== 'string') {
          throw new Error('Missing or invalid truck_id');
        }

        if (departure.latitude < -90 || departure.latitude > 90 ||
            destination.latitude < -90 || destination.latitude > 90 ||
            departure.longitude < -180 || departure.longitude > 180 ||
            destination.longitude < -180 || destination.longitude > 180) {
          throw new Error('Coordinates out of valid range');
        }

        console.log(`Setting route for truck ${truck_id}`);
        console.log(`   From: [${departure.latitude}, ${departure.longitude}]`);
        console.log(`   To: [${destination.latitude}, ${destination.longitude}]`);

        const osrmUrl = `http://osrm:5000/route/v1/truck/${departure.longitude},${departure.latitude};${destination.longitude},${destination.latitude}?geometries=geojson&overview=full&steps=true&alternatives=true&alternatives_number=3&continue_straight=false`;
        console.log(`Requesting OSRM routes with alternatives`);

        const response = await axios.get(osrmUrl, {
          timeout: 20000,
          headers: { 'Accept': 'application/json' },
          validateStatus: (status) => status < 500,
        });

        if (response.status !== 200) {
          throw new Error(`OSRM service returned status ${response.status}: ${response.data?.message || 'Unknown error'}`);
        }

        if (!response.data.routes || response.data.routes.length === 0) {
          throw new Error('No valid routes found from OSRM - check if coordinates are accessible by truck');
        }

        const processedRoutes = response.data.routes.map((route_data, index) => {
          const waypoints = route_data.geometry.coordinates.map(([lon, lat]) => ({
            latitude: lat,
            longitude: lon,
          }));

          const distanceKm = route_data.distance / 1000;
          const durationMinutes = route_data.duration / 60;
          const avgSpeedKmh = (distanceKm / (durationMinutes / 60)) || 50;

          let routeType, routeDescription;
          if (index === 0) {
            routeType = 'fastest';
            routeDescription = 'Fastest Route';
          } else if (distanceKm < response.data.routes[0].distance / 1000) {
            routeType = 'shortest';
            routeDescription = 'Shortest Route';
          } else {
            routeType = 'alternative';
            routeDescription = `Alternative Route ${index}`;
          }

          return {
            id: `route_${index}`,
            type: routeType,
            description: routeDescription,
            waypoints,
            distance: route_data.distance,
            duration: route_data.duration,
            distanceKm: Math.round(distanceKm * 10) / 10,
            durationMinutes: Math.round(durationMinutes),
            avgSpeedKmh: Math.round(avgSpeedKmh),
            isMain: index === 0,
            geometry: route_data.geometry
          };
        });

        console.log(`OSRM returned ${processedRoutes.length} routes:`);
        processedRoutes.forEach((route, i) => {
          console.log(`   Route ${i + 1} (${route.type}): ${route.distanceKm} km, ${route.durationMinutes} min`);
        });

        const mainRoute = processedRoutes[0];
        const routeUpdateMessage = {
          truck_id,
          route: mainRoute.waypoints,
          destination_name: `Custom Destination (${destination.latitude.toFixed(4)}, ${destination.longitude.toFixed(4)})`,
          timestamp: new Date().toISOString(),
          distance: mainRoute.distance,
          duration: mainRoute.duration,
          departure: {
            latitude: departure.latitude,
            longitude: departure.longitude
          },
          destination: {
            latitude: destination.latitude,
            longitude: destination.longitude
          },
          alternatives: processedRoutes.slice(1)
        };

        console.log('Sending route update to Python simulation via Kafka...');

        try {
          await routeProducer.send({
            topic: 'truck-route-updates',
            messages: [{
              key: truck_id,
              value: JSON.stringify(routeUpdateMessage),
            }],
          });
          console.log(`Route update sent to simulation for ${truck_id}`);
        } catch (kafkaError) {
          console.error('Failed to send to Kafka:', kafkaError.message);
          try {
            await routeProducer.connect();
            await routeProducer.send({
              topic: 'truck-route-updates',
              messages: [{
                key: truck_id,
                value: JSON.stringify(routeUpdateMessage),
              }],
            });
            console.log(`Route update sent to simulation for ${truck_id} (retry succeeded)`);
          } catch (retryError) {
            throw new Error(`Failed to send route to simulation: ${retryError.message}`);
          }
        }

        const frontendRouteUpdate = {
          truck_id,
          routes: processedRoutes,
          mainRoute: mainRoute,
          destination_name: routeUpdateMessage.destination_name,
          timestamp: routeUpdateMessage.timestamp,
          totalAlternatives: processedRoutes.length - 1
        };

        io.emit('truckMultiRouteUpdate', frontendRouteUpdate);
        console.log(`Multi-route update sent to frontend for ${truck_id}`);

        socket.emit('routeSetSuccess', {
          truck_id,
          message: `${processedRoutes.length} routes calculated for ${truck_id}`,
          mainRoute: {
            waypoints: mainRoute.waypoints.length,
            distance: mainRoute.distanceKm,
            duration: mainRoute.durationMinutes
          },
          alternatives: processedRoutes.length - 1
        });

      } catch (error) {
        console.error('Error setting route:', error.message);
        
        if (error.response) {
          console.error('Response error:', error.response.status, error.response.data);
        } else if (error.request) {
          console.error('Request error:', error.request);
        }
        
        socket.emit('routeError', {
          message: error.message,
          truck_id: route?.truck_id || null,
          details: error.response?.data || null,
          timestamp: new Date().toISOString()
        });
      }
    });

    socket.on('ping', () => {
      socket.emit('pong');
    });

    socket.on('disconnect', (reason) => {
      console.log('Client disconnected:', socket.id, 'Reason:', reason);
    });
  });

  runConsumer(io).catch((error) => {
    console.error('Consumer startup failed:', error);
    process.exit(1);
  });

  process.on('SIGINT', async () => {
    console.log('Shutting down WebSocket server...');
    await routeProducer.disconnect();
    io.close();
    process.exit(0);
  });

  return io;
};

module.exports = { initializeWebSocket };