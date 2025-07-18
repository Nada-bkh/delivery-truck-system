api_version = 1

function node_function(node, result)
  -- Skip node processing to avoid errors
end

function way_function(way, result)
  local highway = way:get_value_by_key("highway")
  local access = way:get_value_by_key("access")
  local maxweight = tonumber(way:get_value_by_key("maxweight")) or 100
  local maxheight = tonumber(way:get_value_by_key("maxheight")) or 5
  local destination = way:get_value_by_key("destination")
  local route = way:get_value_by_key("route")

  if route == "ferry" or not highway then
    result.forward_mode = mode.inaccessible
    result.backward_mode = mode.inaccessible
    return
  end

  if access == "no" or access == "private" or destination == "parking" then
    result.forward_mode = mode.inaccessible
    result.backward_mode = mode.inaccessible
    return
  end

  if maxweight < 20 or maxheight < 4.5 then
    result.forward_mode = mode.inaccessible
    result.backward_mode = mode.inaccessible
    return
  end

  local speed = {
    motorway = 80,
    trunk = 70,
    primary = 60,
    secondary = 50,
    tertiary = 40,
    unclassified = 30,
    residential = 20,
  }

  result.forward_mode = mode.driving
  result.backward_mode = mode.driving
  result.forward_speed = speed[highway] or 30
  result.backward_speed = speed[highway] or 30
  result.weight = 1.0
end

function turn_function(turn)
  turn.duration = 10
  if turn.angle > 90 or turn.angle < -90 then
    turn.duration = turn.duration + 20
  end
end