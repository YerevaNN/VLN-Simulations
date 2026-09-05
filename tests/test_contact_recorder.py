import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"simulation"))
from contact_recorder import evaluate_contacts, TerrainClearanceObserver, ContactRecorder, is_physical_contact

def row(t,x=0,y=0,z=.15,speed=0):
    return dict(sim_time_s=t,x_enu_m=x,y_enu_m=y,z_enu_m=z,
                vx_enu_mps=speed,vy_enu_mps=0,vz_enu_mps=0)
def event(t,external="/World/Terrain"):
    return dict(sim_time_s=t,actor0="/World/X500v2/body",actor1=external,event_type="found",
                contact_count=1,max_impulse_ns=.1,min_separation_m=0.0)
def meta(count):
    return dict(version=1,coverage="collidable_geometry_only",vehicle_root="/World/X500v2",
                monitored_rigid_bodies=["/World/X500v2/body"],vehicle_collider_count=1,
                physics_steps=100,contact_reports_received=count,contact_rows_written=count,
                first_sim_time_s=0,last_sim_time_s=2,maximum_step_gap_s=.02)
class ContactTests(unittest.TestCase):
    def test_allowed_startup_and_slow_landing(self):
        contacts = [event(0),event(2)]
        outcome=evaluate_contacts(contacts,[row(0),row(1,z=3),row(2)],meta(2))
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["allowed_ground_contacts"],2)
    def test_obstacle_contact_rejected_even_near_launch(self):
        outcome=evaluate_contacts([event(0,"/World/Landmarks/Rock")],[row(0)],meta(1))
        self.assertFalse(outcome["success"])
        self.assertEqual(len(outcome["collisions"]),1)
    def test_terrain_contact_away_from_pad_rejected(self):
        outcome=evaluate_contacts([event(1)],[row(0),row(1,x=10)],meta(1))
        self.assertFalse(outcome["success"])
    def test_fast_landing_contact_rejected(self):
        outcome=evaluate_contacts([event(2)],[row(0),row(1,z=3),row(2,speed=3)],meta(1))
        self.assertFalse(outcome["success"])
    def test_silent_callback_is_unverified(self):
        self.assertFalse(evaluate_contacts([], [row(0)],meta(0))["verified"])
    def test_missing_state_alignment_rejected(self):
        outcome=evaluate_contacts([event(1)],[row(0)],meta(1))
        self.assertFalse(outcome["success"])
        self.assertTrue(outcome["errors"])
    def test_ground_contact_tracks_found_persist_lost_without_order_dependency(self):
        monitor=ContactRecorder.__new__(ContactRecorder)
        monitor.root="/World/X500v2"
        monitor.active_pairs={}
        contact=dict(event(0),collider0="/World/X500v2/body/shape",collider1="/World/Terrain")
        monitor._track_contact(contact)
        self.assertTrue(monitor.has_ground_contact())
        monitor._track_contact(dict(contact,event_type="persists"))
        self.assertTrue(monitor.has_ground_contact())
        lost=dict(contact,event_type="lost",actor0=contact["actor1"],actor1=contact["actor0"],
                  collider0=contact["collider1"],collider1=contact["collider0"])
        monitor._track_contact(lost)
        self.assertFalse(monitor.has_ground_contact())
        monitor._track_contact(dict(contact,actor1="/World/Landmarks/Bridge"))
        self.assertFalse(monitor.has_ground_contact())

    def test_truncated_contact_monitor_is_unverified(self):
        metadata=meta(1)
        metadata["last_sim_time_s"]=.01
        outcome=evaluate_contacts([event(0)],[row(0),row(1),row(2)],metadata)
        self.assertFalse(outcome["verified"])

    def test_external_only_pair_is_invalid(self):
        contact=dict(event(0),actor0="/World/NotTheDrone")
        outcome=evaluate_contacts([contact],[row(0),row(2)],meta(1))
        self.assertFalse(outcome["success"])
        self.assertTrue(any("exactly one drone" in e for e in outcome["errors"]))

    def test_lost_event_timestamp_checked(self):
        contact=dict(event(float("nan")),event_type="lost")
        outcome=evaluate_contacts([contact],[row(0),row(2)],meta(1))
        self.assertFalse(outcome["success"])
        self.assertTrue(any("timestamp" in e for e in outcome["errors"]))

    def test_predictive_manifold_does_not_establish_impact_or_ground_support(self):
        proximity=dict(event(0),min_separation_m=1.04,max_impulse_ns=0.0,
                       collider0="/World/X500v2/body/shape",collider1="/World/Terrain")
        self.assertFalse(is_physical_contact(proximity))
        monitor=ContactRecorder.__new__(ContactRecorder)
        monitor.root="/World/X500v2"
        monitor.active_pairs={}
        monitor._track_contact(proximity)
        self.assertFalse(monitor.has_ground_contact())
        outcome=evaluate_contacts([proximity],[row(0,z=2),row(2,z=3)],meta(1))
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["proximity_reports"],1)
        self.assertFalse(outcome["collisions"])

    def test_small_impulse_and_zero_force_penetration_still_count(self):
        self.assertTrue(is_physical_contact(dict(event(0),min_separation_m=.01,max_impulse_ns=1e-10)))
        self.assertTrue(is_physical_contact(dict(event(0),min_separation_m=-1e-8,max_impulse_ns=0)))
        self.assertFalse(is_physical_contact(dict(event(0),contact_count=0)))

    def test_nonfinite_separation_or_impulse_rejected(self):
        for field in ("max_impulse_ns","min_separation_m"):
            with self.assertRaises(ValueError):
                is_physical_contact(dict(event(0),**{field:float("nan")}))

    def test_terrain_clearance_is_explicit_proxy(self):
        observer=TerrainClearanceObserver(lambda x,y: x/2,radius_m=.5)
        self.assertEqual(observer.sample((2,0,5)),3.5)
        observer.sample((0,0,.15),in_flight=False)
        self.assertEqual(observer.summary()["minimum_in_flight_clearance_estimate_m"],3.5)
        self.assertEqual(observer.summary()["scope"],"analytic_terrain_height_proxy")
if __name__=="__main__":
    unittest.main()

