# Used by `sam build`. The Lambda package is the winback folder with the settings files beside it.
build-SimulationFunction:
	mkdir -p "$(ARTIFACTS_DIR)"
	cp -r src/winback "$(ARTIFACTS_DIR)/"
	rm -rf "$(ARTIFACTS_DIR)/winback/__pycache__"
	cp settings.toml first_drafts.toml prewritten.toml fact_sheet.toml "$(ARTIFACTS_DIR)/"

# The web app ships the same package: the page sits inside the winback folder.
build-WebFunction: build-SimulationFunction
