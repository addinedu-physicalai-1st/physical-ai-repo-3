#include "ddooby_controller/simulator/manufacturing_layout_utils.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace ddooby_controller::manufacturing_task {

std::string readTextFile(const std::string& path) {
  std::ifstream stream(path);
  if (!stream) {
    throw std::runtime_error("failed to open " + path);
  }
  std::ostringstream buffer;
  buffer << stream.rdbuf();
  return buffer.str();
}

std::string joinPath(const std::string& left, const std::string& right) {
  if (left.empty() || left.back() == '/') {
    return left + right;
  }
  return left + "/" + right;
}

std::string effectiveManufacturingLayoutPath(const std::string& package_share_directory,
                                             const std::string& requested_layout_path) {
  return requested_layout_path.empty()
             ? joinPath(package_share_directory, "assets/manufacturing_world/layout.json")
             : requested_layout_path;
}

std::string extractStringValue(const std::string& text, const std::string& key) {
  const std::string marker = "\"" + key + "\"";
  const auto key_pos = text.find(marker);
  if (key_pos == std::string::npos) {
    throw std::runtime_error("missing string key '" + key + "'");
  }
  const auto colon_pos = text.find(':', key_pos + marker.size());
  const auto first_quote = text.find('"', colon_pos);
  const auto second_quote = text.find('"', first_quote + 1);
  if (colon_pos == std::string::npos || first_quote == std::string::npos ||
      second_quote == std::string::npos) {
    throw std::runtime_error("invalid string value for key '" + key + "'");
  }
  return text.substr(first_quote + 1, second_quote - first_quote - 1);
}

std::vector<double> parseDoubles(const std::string& text) {
  std::string normalized = text;
  for (char& character : normalized) {
    if (character == ',' || character == '\n' || character == '\t') {
      character = ' ';
    }
  }

  std::istringstream stream(normalized);
  std::vector<double> values;
  double value = 0.0;
  while (stream >> value) {
    values.push_back(value);
  }
  return values;
}

Eigen::Vector3d extractVector3Value(const std::string& text, const std::string& key) {
  const std::string marker = "\"" + key + "\"";
  const auto key_pos = text.find(marker);
  if (key_pos == std::string::npos) {
    throw std::runtime_error("missing vector key '" + key + "'");
  }
  const auto open_bracket = text.find('[', key_pos + marker.size());
  const auto close_bracket = text.find(']', open_bracket);
  if (open_bracket == std::string::npos || close_bracket == std::string::npos) {
    throw std::runtime_error("invalid vector value for key '" + key + "'");
  }
  const auto values = parseDoubles(text.substr(open_bracket + 1, close_bracket - open_bracket - 1));
  if (values.size() != 3) {
    throw std::runtime_error("vector key '" + key + "' does not have three values");
  }
  return Eigen::Vector3d(values[0], values[1], values[2]);
}

bool extractTagText(const std::string& text, const std::string& tag, std::string& value) {
  const std::string open_tag = "<" + tag + ">";
  const std::string close_tag = "</" + tag + ">";
  const auto open_pos = text.find(open_tag);
  if (open_pos == std::string::npos) {
    return false;
  }
  const auto value_start = open_pos + open_tag.size();
  const auto close_pos = text.find(close_tag, value_start);
  if (close_pos == std::string::npos) {
    return false;
  }
  value = text.substr(value_start, close_pos - value_start);
  return true;
}

std::string extractJsonObjectForModel(const std::string& layout_text,
                                      const std::string& target_model) {
  const std::string marker = "\"name\": \"" + target_model + "\"";
  const auto name_pos = layout_text.find(marker);
  if (name_pos == std::string::npos) {
    throw std::runtime_error("target model '" + target_model + "' is missing from layout");
  }

  const auto object_start = layout_text.rfind('{', name_pos);
  if (object_start == std::string::npos) {
    throw std::runtime_error("failed to locate model object for '" + target_model + "'");
  }

  int depth = 0;
  for (size_t i = object_start; i < layout_text.size(); ++i) {
    if (layout_text[i] == '{') {
      ++depth;
    } else if (layout_text[i] == '}') {
      --depth;
      if (depth == 0) {
        return layout_text.substr(object_start, i - object_start + 1);
      }
    }
  }

  throw std::runtime_error("unterminated model object for '" + target_model + "'");
}

std::vector<CollisionPrimitiveSpec> parseCollisionPrimitives(const std::string& sdf_text) {
  std::vector<CollisionPrimitiveSpec> primitives;
  size_t search_pos = 0;
  while (true) {
    const auto collision_start = sdf_text.find("<collision", search_pos);
    if (collision_start == std::string::npos) {
      break;
    }
    const auto collision_end = sdf_text.find("</collision>", collision_start);
    if (collision_end == std::string::npos) {
      break;
    }
    const auto block = sdf_text.substr(
        collision_start, collision_end + std::string("</collision>").size() - collision_start);
    search_pos = collision_end + std::string("</collision>").size();

    CollisionPrimitiveSpec primitive;
    bool has_geometry = false;
    std::string size_text;
    if (extractTagText(block, "size", size_text)) {
      const auto size_values = parseDoubles(size_text);
      if (size_values.size() == 3) {
        primitive.type = CollisionPrimitiveSpec::Type::Box;
        primitive.size = Eigen::Vector3d(size_values[0], size_values[1], size_values[2]);
        has_geometry = true;
      }
    } else {
      std::string radius_text;
      std::string length_text;
      if (extractTagText(block, "radius", radius_text) &&
          extractTagText(block, "length", length_text)) {
        const auto radius_values = parseDoubles(radius_text);
        const auto length_values = parseDoubles(length_text);
        if (radius_values.size() == 1 && length_values.size() == 1) {
          const double diameter = radius_values[0] * 2.0;
          primitive.type = CollisionPrimitiveSpec::Type::Cylinder;
          primitive.radius = radius_values[0];
          primitive.length = length_values[0];
          primitive.size = Eigen::Vector3d(diameter, diameter, length_values[0]);
          has_geometry = true;
        }
      }
    }
    if (!has_geometry) {
      continue;
    }

    std::string pose_text;
    if (extractTagText(block, "pose", pose_text)) {
      const auto pose_values = parseDoubles(pose_text);
      if (pose_values.size() >= 3) {
        primitive.center = Eigen::Vector3d(pose_values[0], pose_values[1], pose_values[2]);
      }
      if (pose_values.size() >= 6) {
        primitive.rpy = Eigen::Vector3d(pose_values[3], pose_values[4], pose_values[5]);
      }
    }

    primitives.push_back(primitive);
  }
  return primitives;
}

std::vector<CollisionBox> parseCollisionBoxes(const std::string& sdf_text) {
  std::vector<CollisionBox> boxes;
  for (const CollisionPrimitiveSpec& primitive : parseCollisionPrimitives(sdf_text)) {
    boxes.push_back(CollisionBox{primitive.center, primitive.size});
  }
  return boxes;
}

}  // namespace ddooby_controller::manufacturing_task
