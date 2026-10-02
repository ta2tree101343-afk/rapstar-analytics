# SAM makefile-builder for CollectorFunction.
#
# SAM invokes `make build-CollectorFunction` with:
#   - CWD    = a temp copy of this directory (collector-lambda/)
#   - ARTIFACTS_DIR = the staging directory whose contents become the Lambda
#                    zip root
#
# We assemble the zip so that `collector/` sits at the root — this preserves
# the existing `collector.aws.handler.lambda_handler` handler string and the
# in-package relative imports (`from ..classifier import ...`).
#
# Runtime dependencies are pinned in ./requirements.txt (a superset of what
# the Lambda actually needs to import; boto3 is provided by the Lambda
# runtime and is intentionally NOT vendored to avoid version drift).

# The `collector-src` entry inside this directory is a symlink to the real
# collector/ package (see the `ln -s` in the initial setup, tracked in git).
# SAM's build workflow copies CodeUri to a scratch directory with symlinks
# resolved, so at make-time CWD contains a real copy of the source tree.
COLLECTOR_SRC := collector-src

build-CollectorFunction:
	@echo ">> Staging collector package into $(ARTIFACTS_DIR)/collector"
	mkdir -p "$(ARTIFACTS_DIR)/collector"
	cp -R $(COLLECTOR_SRC)/. "$(ARTIFACTS_DIR)/collector/"
	find "$(ARTIFACTS_DIR)/collector" -type d -name "__pycache__" -prune -exec rm -rf {} +
	find "$(ARTIFACTS_DIR)/collector" -type f -name "*.pyc" -delete
	@echo ">> Installing runtime dependencies into $(ARTIFACTS_DIR) (Linux arm64 wheels)"
	@# --platform / --python-version / --only-binary force pip to fetch
	@# wheels matching the Lambda runtime (Linux, aarch64, CPython 3.13),
	@# regardless of the developer's local architecture (e.g. macOS arm64).
	@# Without these, SQLAlchemy / charset_normalizer would install their
	@# darwin .so files and fail at runtime in Lambda.
	python3 -m pip install \
	    --disable-pip-version-check \
	    --no-cache-dir \
	    --no-compile \
	    --platform manylinux2014_aarch64 \
	    --python-version 3.13 \
	    --implementation cp \
	    --abi cp313 \
	    --only-binary=:all: \
	    --target "$(ARTIFACTS_DIR)" \
	    -r requirements.txt
	@echo ">> Removing dist-info metadata directories (optional zip diet)"
	find "$(ARTIFACTS_DIR)" -maxdepth 1 -type d -name "*.dist-info" -prune -exec rm -rf {} +
	@echo ">> Build complete"
