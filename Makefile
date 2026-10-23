# Used by `sam build`. The Lambda package is the winback folder with the settings files beside it.
build-SimulationFunction:
	mkdir -p "$(ARTIFACTS_DIR)"
	cp -r src/winback "$(ARTIFACTS_DIR)/"
	rm -rf "$(ARTIFACTS_DIR)/winback/__pycache__"
	cp settings.toml first_drafts.toml prewritten.toml "$(ARTIFACTS_DIR)/"
