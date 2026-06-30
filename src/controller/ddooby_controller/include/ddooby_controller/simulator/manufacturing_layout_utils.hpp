#pragma once

#include <Eigen/Geometry>
#include <string>
#include <vector>

#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task {

std::string readTextFile(const std::string& path);

std::string joinPath(const std::string& left, const std::string& right);

std::string effectiveManufacturingLayoutPath(const std::string& package_share_directory,
                                             const std::string& requested_layout_path);

std::string extractStringValue(const std::string& text, const std::string& key);

std::vector<double> parseDoubles(const std::string& text);

Eigen::Vector3d extractVector3Value(const std::string& text, const std::string& key);

bool extractTagText(const std::string& text, const std::string& tag, std::string& value);

std::string extractJsonObjectForModel(const std::string& layout_text,
                                      const std::string& target_model);

std::vector<CollisionPrimitiveSpec> parseCollisionPrimitives(const std::string& sdf_text);

std::vector<CollisionBox> parseCollisionBoxes(const std::string& sdf_text);

}  // namespace ddooby_controller::manufacturing_task
