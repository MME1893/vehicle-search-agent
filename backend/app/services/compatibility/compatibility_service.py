

class CompatibilityService:
    def __init__(self, compat, vehicles, oils):
        self.compat, self.vehicles, self.oils = compat, vehicles, oils

    def create_event(self, data: dict):
        if not self.vehicles.get_by_id(data["vehicle_id"]) or not self.oils.get_by_id(
            data["engine_oil_id"]
        ):
            raise LookupError("vehicle or engine oil not found")
        data.setdefault("match_method", "MANUAL")
        return self.compat.create(data)
