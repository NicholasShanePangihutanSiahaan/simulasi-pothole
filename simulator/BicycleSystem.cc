// A virtual rider applies propulsion, lateral tire assistance and balance torque.
// Vertical motion, pitch, gravity and wheel/road contact remain in Gazebo physics.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <mutex>
#include <gz/math/Pose3.hh>
#include <gz/msgs/pose.pb.h>
#include <gz/msgs/twist.pb.h>
#include <gz/msgs/odometry.pb.h>
#include <gz/plugin/Register.hh>
#include <gz/sim/System.hh>
#include <gz/sim/Link.hh>
#include <gz/sim/Model.hh>
#include <gz/sim/Util.hh>
#include <gz/sim/components/JointForceCmd.hh>
#include <gz/sim/components/JointPosition.hh>
#include <gz/sim/components/JointVelocity.hh>
#include <gz/sim/components/LinearVelocityCmd.hh>
#include <gz/sim/components/AngularVelocityCmd.hh>
#include <gz/transport/Node.hh>

namespace capstone {
class BicycleSystem final : public gz::sim::System,
    public gz::sim::ISystemConfigure, public gz::sim::ISystemPreUpdate,
    public gz::sim::ISystemPostUpdate {
  gz::sim::Model model;
  gz::sim::Link frame;
  gz::sim::Entity steering{gz::sim::kNullEntity};
  gz::transport::Node node;
  gz::transport::Node::Publisher odom;
  std::mutex mutex;
  double throttle{0}, steer{0}, brake{1};
  bool resetting{false};
  bool clearResetVelocity{false};
  gz::math::Pose3d resetPose;
  std::chrono::steady_clock::time_point commandTime{};
  double lastPublish{-1};
  double headingTarget{0};

 public:
  void Configure(const gz::sim::Entity &entity,
      const std::shared_ptr<const sdf::Element> &,
      gz::sim::EntityComponentManager &ecm, gz::sim::EventManager &) override {
    model = gz::sim::Model(entity);
    frame = gz::sim::Link(model.LinkByName(ecm, "frame"));
    frame.EnableVelocityChecks(ecm);
    steering = model.JointByName(ecm, "steering");
    ecm.CreateComponent(steering, gz::sim::components::JointPosition());
    ecm.CreateComponent(steering, gz::sim::components::JointVelocity());
    node.Subscribe("/capstone/control", &BicycleSystem::Control, this);
    node.Subscribe("/capstone/reset", &BicycleSystem::Reset, this);
    odom = node.Advertise<gz::msgs::Odometry>("/capstone/odometry");
  }
  void Control(const gz::msgs::Twist &msg) {
    std::lock_guard<std::mutex> lock(mutex);
    throttle = std::clamp(msg.linear().x(), -1.0, 1.0);
    brake = std::clamp(msg.linear().y(), 0.0, 1.0);
    steer = std::clamp(msg.angular().z(), -1.0, 1.0);
    commandTime = std::chrono::steady_clock::now();
  }
  void Reset(const gz::msgs::Pose &msg) {
    std::lock_guard<std::mutex> lock(mutex);
    const auto &q = msg.orientation();
    const double yaw = gz::math::Quaterniond(q.w(), q.x(), q.y(), q.z()).Yaw();
    resetPose = gz::math::Pose3d(msg.position().x(), msg.position().y(), .72, 0, 0, yaw);
    resetting = true;
    throttle = steer = 0;
    brake = 1;
  }
  void PreUpdate(const gz::sim::UpdateInfo &info,
      gz::sim::EntityComponentManager &ecm) override {
    if (info.paused) return;
    std::lock_guard<std::mutex> lock(mutex);
    if (clearResetVelocity) {
      for (auto entity : model.Links(ecm)) {
        ecm.RemoveComponent<gz::sim::components::LinearVelocityCmd>(entity);
        ecm.RemoveComponent<gz::sim::components::AngularVelocityCmd>(entity);
      }
      clearResetVelocity = false;
    }
    if (resetting) {
      model.SetWorldPoseCmd(ecm, resetPose);
      headingTarget = resetPose.Rot().Yaw();
      for (auto entity : model.Links(ecm)) {
        gz::sim::Link link(entity);
        link.SetLinearVelocity(ecm, gz::math::Vector3d::Zero);
        link.SetAngularVelocity(ecm, gz::math::Vector3d::Zero);
      }
      resetting = false;
      clearResetVelocity = true;
      return;
    }
    const auto pose = gz::sim::worldPose(frame.Entity(), ecm);
    const auto worldV = frame.WorldLinearVelocity(ecm).value_or(gz::math::Vector3d::Zero);
    const auto worldW = frame.WorldAngularVelocity(ecm).value_or(gz::math::Vector3d::Zero);
    const auto bodyW = pose.Rot().RotateVectorReverse(worldW);
    const bool stale = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - commandTime).count() > .6;
    const double t = stale ? 0 : throttle;
    double b = stale ? 1 : brake;
    if (pose.Pos().X() < -2 || pose.Pos().X() > 144 || std::abs(pose.Pos().Y()) > 6.6) b = 1;
    const double yaw = pose.Rot().Yaw();
    const double v = worldV.X()*std::cos(yaw) + worldV.Y()*std::sin(yaw);
    const double lateralV = -worldV.X()*std::sin(yaw) + worldV.Y()*std::cos(yaw);
    const double delta = steer * .48;
    const double desiredYawRate = v * std::tan(delta) / 1.16;
    // Virtual rider balances even at a standstill. Roll lean is modest for an exhibit.
    const double lean = std::clamp(-std::atan(v * desiredYawRate / 9.81), -.20, .20);
    const double rollTorque = 3500 * (lean - pose.Rot().Roll()) - 350 * bodyW.X();
    headingTarget += desiredYawRate * std::chrono::duration<double>(info.dt).count();
    const double headingError = std::atan2(std::sin(headingTarget-yaw), std::cos(headingTarget-yaw));
    const double yawTorque = std::clamp(1600*headingError + 320*(desiredYawRate-worldW.Z()), -1200., 1200.);
    const double limitedThrottle = t > 0 && v > 6.5 ? t * std::clamp((7.0-v)/.5, 0., 1.) : t;
    const double drive = 150 * limitedThrottle - 2.5 * v - .65 * v * std::abs(v) - b * 250 * v;
    const double forceX = std::clamp(drive, -380., 210.);
    const double forceY = std::clamp(-650 * lateralV, -500., 500.);
    // Only horizontal force: do not cancel contact response or gravity.
    gz::math::Vector3d force(std::cos(yaw)*forceX-std::sin(yaw)*forceY,
                            std::sin(yaw)*forceX+std::cos(yaw)*forceY, 0);
    const double pitchTorque = -8*bodyW.Y();
    gz::math::Vector3d torque(std::cos(yaw)*rollTorque-std::sin(yaw)*pitchTorque,
                             std::sin(yaw)*rollTorque+std::cos(yaw)*pitchTorque, yawTorque);
    frame.AddWorldWrench(ecm, force, torque);
    const auto pos = ecm.Component<gz::sim::components::JointPosition>(steering);
    const auto vel = ecm.Component<gz::sim::components::JointVelocity>(steering);
    double angle = pos && !pos->Data().empty() ? pos->Data()[0] : 0;
    double rate = vel && !vel->Data().empty() ? vel->Data()[0] : 0;
    ecm.SetComponentData<gz::sim::components::JointForceCmd>(steering,
        {std::clamp(700*(delta-angle)-45*rate, -220., 220.)});
  }
  void PostUpdate(const gz::sim::UpdateInfo &info,
      const gz::sim::EntityComponentManager &ecm) override {
    if (info.paused) return;
    const double now = std::chrono::duration<double>(info.simTime).count();
    if (now >= lastPublish && now - lastPublish < 1.0/30) return;
    lastPublish = now;
    const auto p = gz::sim::worldPose(frame.Entity(), ecm);
    const auto v = frame.WorldLinearVelocity(ecm).value_or(gz::math::Vector3d::Zero);
    const auto w = frame.WorldAngularVelocity(ecm).value_or(gz::math::Vector3d::Zero);
    gz::msgs::Odometry msg;
    msg.mutable_header()->mutable_stamp()->set_sec(static_cast<int64_t>(now));
    msg.mutable_header()->mutable_stamp()->set_nsec(static_cast<int32_t>((now-std::floor(now))*1e9));
    auto position = msg.mutable_pose()->mutable_position();
    position->set_x(p.Pos().X()); position->set_y(p.Pos().Y()); position->set_z(p.Pos().Z());
    auto q = msg.mutable_pose()->mutable_orientation();
    q->set_w(p.Rot().W()); q->set_x(p.Rot().X()); q->set_y(p.Rot().Y()); q->set_z(p.Rot().Z());
    auto linear = msg.mutable_twist()->mutable_linear();
    linear->set_x(v.X()); linear->set_y(v.Y()); linear->set_z(v.Z());
    auto angular = msg.mutable_twist()->mutable_angular();
    angular->set_x(w.X()); angular->set_y(w.Y()); angular->set_z(w.Z());
    odom.Publish(msg);
  }
};
}
GZ_ADD_PLUGIN(capstone::BicycleSystem, gz::sim::System,
    gz::sim::ISystemConfigure, gz::sim::ISystemPreUpdate, gz::sim::ISystemPostUpdate)
GZ_ADD_PLUGIN_ALIAS(capstone::BicycleSystem, "capstone::BicycleSystem")
