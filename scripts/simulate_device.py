"""One-shot simulated event generator for local development."""

import argparse
import json

from app.device_integrations.simulator import simulated_location


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--latitude", required=True, type=float)
    parser.add_argument("--longitude", required=True, type=float)
    parser.add_argument("--battery", default=80, type=int)
    args = parser.parse_args()
    event = simulated_location(
        args.device_id,
        args.latitude,
        args.longitude,
        args.battery,
    )
    print(json.dumps(event.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
