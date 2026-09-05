"""Actual PhysX contact reports and explicitly approximate terrain clearance.

The subscription API is the installed Isaac 5.1 ContactReportDemo API. Visual
assets without collision schemas cannot appear in these reports.
"""
import bisect
import json
import math


def is_physical_contact(row):
    """PhysX reports separated manifolds inside contactOffset before impact.

    Positive separation with zero impulse is proximity only. Applied impulse or
    nonpositive separation establishes response/contact without inventing a force
    threshold. Lost/empty manifolds never establish physical support.
    Reference: PhysX AdvancedCollisionDetection and PxContactPairPoint.
    """
    if row.get("event_type") == "lost":
        return False
    count = int(row["contact_count"])
    impulse = float(row["max_impulse_ns"])
    separation = float(row["min_separation_m"])
    if count < 0 or not math.isfinite(impulse) or impulse < 0 or not math.isfinite(separation):
        raise ValueError("Invalid PhysX contact count, impulse or separation")
    return count > 0 and (impulse > 0 or separation <= 0)


class ContactRecorder:
    def __init__(self, stage, vehicle_root, output_path):
        from pxr import PhysxSchema, UsdPhysics, Usd, PhysicsSchemaTools
        from omni.physx import get_physx_simulation_interface
        from omni.physx.bindings._physx import ContactEventType
        self.root = vehicle_root.rstrip("/")
        self.pending = []
        self.active_pairs = {}
        self.maximum_step_gap_s = 0.0
        self.callback_error = None
        self.steps = 0
        self.reports = 0
        self.written = 0
        self.first_time = None
        self.last_time = None
        self.stream = open(output_path, "w", encoding="utf-8")
        self.rigid_bodies = []
        self.collider_count = 0
        self._subscription = None
        root = stage.GetPrimAtPath(vehicle_root)
        if not root.IsValid():
            self.stream.close()
            raise ValueError("Contact monitor vehicle root does not exist")
        for prim in Usd.PrimRange(root):
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr().Set(0.0)
                self.rigid_bodies.append(str(prim.GetPath()))
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                self.collider_count += 1
        if not self.rigid_bodies or not self.collider_count:
            self.stream.close()
            raise ValueError("Contact monitor found no drone rigid bodies or colliders")
        def belongs(path):
            return path == self.root or path.startswith(self.root + "/")
        def callback(headers, data):
            try:
                for header in headers:
                    actor0 = str(PhysicsSchemaTools.intToSdfPath(header.actor0))
                    actor1 = str(PhysicsSchemaTools.intToSdfPath(header.actor1))
                    if belongs(actor0) == belongs(actor1):
                        continue
                    self.reports += 1
                    points = [data[i] for i in range(header.contact_data_offset,
                              header.contact_data_offset + header.num_contact_data)]
                    impulse = max((math.sqrt(sum(float(v)**2 for v in p.impulse)) for p in points), default=0.0)
                    separation = min((float(p.separation) for p in points), default=0.0)
                    event = ("found" if header.type == ContactEventType.CONTACT_FOUND else
                             "lost" if header.type == ContactEventType.CONTACT_LOST else "persists")
                    row = {"actor0": actor0, "actor1": actor1,
                        "collider0": str(PhysicsSchemaTools.intToSdfPath(header.collider0)),
                        "collider1": str(PhysicsSchemaTools.intToSdfPath(header.collider1)),
                        "event_type": event, "contact_count": int(header.num_contact_data),
                        "max_impulse_ns": impulse, "min_separation_m": separation}
                    self._track_contact(row)
                    self.pending.append(row)
            except Exception as exc:
                self.callback_error = str(exc)
        self._callback = callback
        self._subscription = get_physx_simulation_interface().subscribe_contact_report_events(callback)

    def _track_contact(self, row):
        # Sort actor/collider pairs so contact header ordering cannot leave stale state.
        key = tuple(sorted(((row["actor0"], row["collider0"]),
                            (row["actor1"], row["collider1"]))))
        if row["event_type"] == "lost":
            self.active_pairs.pop(key, None)
        else:
            self.active_pairs[key] = row

    def has_ground_contact(self):
        for row in self.active_pairs.values():
            external = [row[key] for key in ("actor0", "actor1")
                        if not (row[key] == self.root or row[key].startswith(self.root + "/"))]
            if (len(external) == 1 and external[0] in ("/World/Terrain", "/World/groundPlane")
                    and is_physical_contact(row)):
                return True
        return False

    def sample(self, sim_time_s):
        if self.callback_error:
            raise RuntimeError("PhysX contact callback failed: " + self.callback_error)
        if self.last_time is not None:
            gap = sim_time_s - self.last_time
            if gap <= 0:
                raise ValueError("Contact monitor physics time must advance")
            self.maximum_step_gap_s = max(self.maximum_step_gap_s, gap)
        self.steps += 1
        self.first_time = sim_time_s if self.first_time is None else self.first_time
        self.last_time = sim_time_s
        for row in self.pending:
            self.stream.write(json.dumps({"sim_time_s": float(sim_time_s), **row}) + "\n")
            self.written += 1
        self.pending.clear()

    def close(self):
        self._subscription = None
        if not self.stream.closed:
            # Timeline stop can issue lost events after the last physics step.
            if self.last_time is not None:
                for row in self.pending:
                    self.stream.write(json.dumps({"sim_time_s": float(self.last_time), **row}) + "\n")
                    self.written += 1
                self.pending.clear()
            self.stream.flush()
            self.stream.close()

    def summary(self):
        return {"version": 1, "coverage": "collidable_geometry_only",
                "vehicle_root": self.root, "monitored_rigid_bodies": self.rigid_bodies,
                "vehicle_collider_count": self.collider_count, "physics_steps": self.steps,
                "first_sim_time_s": self.first_time, "last_sim_time_s": self.last_time,
                "maximum_step_gap_s": self.maximum_step_gap_s,
                "contact_reports_received": self.reports, "contact_rows_written": self.written,
                "callback_error": self.callback_error,
                "physical_contact_rule": "nonempty_manifold_and_positive_impulse_or_nonpositive_separation",
                "limitations": "Visual-only vegetation and referenced meshes without CollisionAPI are outside coverage."}


def evaluate_contacts(contacts, states, metadata):
    """Recompute contact classification from recorded state, not generator phases."""
    metadata = metadata or {}
    verified = bool(metadata.get("version") == 1
        and metadata.get("coverage") == "collidable_geometry_only"
        and metadata.get("monitored_rigid_bodies") and metadata.get("vehicle_collider_count", 0) > 0
        and metadata.get("physics_steps", 0) > 0
        and metadata.get("contact_reports_received", 0) > 0
        and metadata.get("contact_rows_written") == len(contacts)
        and metadata.get("contact_reports_received") == len(contacts)
        and not metadata.get("callback_error"))
    collisions, allowed, errors = [], 0, []
    proximity_reports = 0
    times = [float(row["sim_time_s"]) for row in states]
    if not times or any(not math.isfinite(t) for t in times) or any(b <= a for a,b in zip(times,times[1:])):
        return {"success": False, "verified": False, "errors": ["Missing or unordered vehicle states"],
                "collisions": [], "allowed_ground_contacts": 0}
    try:
        first = float(metadata["first_sim_time_s"])
        last = float(metadata["last_sim_time_s"])
        gap = float(metadata["maximum_step_gap_s"])
        covered = (all(math.isfinite(v) for v in (first,last,gap))
                   and times[0]-.05 <= first <= times[0]+.02
                   and times[-1]-.02 <= last <= times[-1]+.05
                   and 0 <= gap <= .025 and metadata["physics_steps"] >= len(states))
    except (KeyError, TypeError, ValueError):
        covered = False
    verified = verified and covered
    if not covered:
        errors.append("Contact monitor does not establish continuous full-episode coverage")
    first_airborne_time = next((r["sim_time_s"] for r in states if r["z_enu_m"] > 2.0), math.inf)
    root = metadata.get("vehicle_root", "/World/X500v2").rstrip("/")
    previous_contact_time = -math.inf
    for contact in contacts:
        try:
            t = float(contact["sim_time_s"])
            if not math.isfinite(t) or t < previous_contact_time:
                raise ValueError("Non-finite or unordered contact timestamp")
            previous_contact_time = t
            # State recording is 50 Hz and physics 250 Hz: nearest sample,
            # with a strict maximum gap, rather than trusting phase annotations.
            index = bisect.bisect_left(times, t)
            candidates = [i for i in (index-1,index) if 0 <= i < len(times)]
            index = min(candidates, key=lambda i: abs(times[i]-t))
            state = states[index]
            if abs(times[index]-t) > .05:
                raise ValueError("Contact has no nearby recorded state")
            actors = [contact["actor0"],contact["actor1"]]
            external = [p for p in actors if not (p == root or p.startswith(root + "/"))]
            if len(external) != 1:
                raise ValueError("Contact must pair exactly one drone actor with one external actor")
            if contact.get("event_type") not in ("found", "persists", "lost"):
                raise ValueError("Unknown contact event type")
            if contact["event_type"] == "lost":
                continue
            if not is_physical_contact(contact):
                proximity_reports += 1
                continue
            terrain = external[0] in ("/World/Terrain", "/World/groundPlane")
            near_pad = math.hypot(state["x_enu_m"],state["y_enu_m"]) <= 2.5 and state["z_enu_m"] <= .9
            speed = math.sqrt(sum(float(state[k])**2 for k in ("vx_enu_mps","vy_enu_mps","vz_enu_mps")))
            safe_ground = terrain and near_pad and (t < first_airborne_time or speed <= .5)
            if safe_ground:
                allowed += 1
            else:
                collisions.append({"sim_time_s":t,"actor0":actors[0],"actor1":actors[1],
                                   "max_impulse_ns":contact.get("max_impulse_ns")})
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(str(exc))
    return {"success": verified and not collisions and not errors, "verified": verified,
            "coverage": "collidable_geometry_only", "collisions": collisions,
            "allowed_ground_contacts": allowed, "proximity_reports": proximity_reports, "errors": errors}


class TerrainClearanceObserver:
    """Height-field proxy only; not a contact or triangle-mesh collision test."""
    def __init__(self, height_function, radius_m=.35):
        self.height_function = height_function
        self.radius_m = radius_m
        self.minimum = None
        self.samples = 0
    def sample(self, position, in_flight=True):
        height = float(self.height_function(float(position[0]),float(position[1])))
        clearance = float(position[2]) - height - self.radius_m
        if in_flight:
            self.minimum = clearance if self.minimum is None else min(self.minimum, clearance)
            self.samples += 1
        return clearance
    def summary(self):
        return {"scope":"analytic_terrain_height_proxy", "vehicle_radius_m":self.radius_m,
                "minimum_in_flight_clearance_estimate_m":self.minimum,"in_flight_samples":self.samples,
                "limitations":"Does not bound sampled mesh interpolation or visual asset clearance."}

