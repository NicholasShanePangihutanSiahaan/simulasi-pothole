#pragma once
#include <algorithm>
#include <cmath>

namespace capstone {
// Limits match the virtual rider's 0.20 rad lean envelope (about 2 m/s²).
class SteeringControl {
 public:
  double angle{0};
  void Reset() { angle = 0; }
  double Update(double input, double speed, double dt) {
    const double limit = std::min(.48, std::atan(1.8 * 1.16 /
        std::max(speed * speed, .01)));
    // Scale the full input range into the allowed angle, rather than
    // saturating small inputs at high speed.
    const double target = std::clamp(input, -1., 1.) * limit;
    // Slew in simulation time, independent of browser and physics frame rates.
    const double step = .9 * std::clamp(dt, 0., .05);
    angle += std::clamp(target - angle, -step, step);
    angle = std::clamp(angle, -limit, limit);
    return angle;
  }
};
}
