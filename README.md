# muframe
##ooi-ui-muframe

Ocean Observatories Initiative - User Interface routes support service for uFrame.

Brief gunicorn service supporting requests for uframe routes from OOI UI Flask App

## Service endpoints
The WSGI service endpoints are listed and defined below:

    /service=alive                              # service= request is operational
    /service=/sensor/inv                        # service= request uFrame data from store
    /service=/sensor/inv/valid_uframe_request   # service= request uFrame data from store
    /uframe=alive                               # uframe=  request is operational
    /uframe=/sensor/inv                         # uframe=  request uFrame data directly (without use of store)
    /uframe=/sensor/inv/valid_uframe_request    # uframe=  request uFrame data directly (without use of store)


### Configuration
Be sure to edit your `muframe.yml` file to the correct host(s), port(s), data root and folders.

Verify the configuration for configuration variables data_root and data_folder exist and have write access:

    data_root: '..'                         # directory where data_folder is located; ensure this directory exists
    data_folder: 'data'                     # folder where data is stored; ensure this folder exists
    uframe_url: 'http://localhost:12575'    # uFrame server url
    uframe_url_root: '/sensor/inv'          # ensure same value as OOI UI services UFRAME_URL_BASE config value

### Service setup
Ensure you have the following:

Operational OOi UI services.

Verify OOI UI services are operational by using a web browser and navigating to:

    http://localhost:4000/arrays


Verify uFrame server is available.

Verify uFrame services are operational by using a web browser and navigating to:

    http://localhost:12575/sensor/inv

Update the muframe configuration file with host, port and base url information.


### Running the services instance
    python muframe.py

### Service Tests
Test your initial setup by running from muframe directory:

    python muframe.py

Verify service is operational by using a web browser and navigating to:

    http://localhost:7090/service=/sensor/inv        # uses data store
    http://localhost:7090/uframe=/sensor/inv         # uses uFrame connection

Exercise service request(s) by using a web browser and navigating to:

    http://localhost:7090/service=/sensor/inv/CP02PMCO/SBS01/01-MOPAK0000/telemetered/mopak_o_dcl_accel
    http://localhost:7090/uframe=/sensor/inv/CP02PMCO/SBS01/01-MOPAK0000/telemetered/mopak_o_dcl_accel

### Configure for use with OOI UI
Verify OOI UI is operational. Stop OOI UI services; edit OOI UI services config.yml for your environment:

        UFRAME_URL: 'http://localhost:7090/service='  # Retain current setting for reference
        UFRAME_URL_BASE: '/sensor/inv'                # Ensure same as muframe 'uframe_url_root' config variable.

Start the OOI UI Services.

Exercise muframe service request(s) by using a web browser and navigating to:

    http://localhost:5000/#

    Log into OOI UI

    Navigate within TOC to 'Coastal Pioneer Central Offshore Platform Mooring' wire-following profiler data.


### Trouble Shooting

In the event of an error, corrective action checks include:

    - If the muframe services do not initialize, ensure the data_folder and data_root exist and are write enabled.
    - If the muframe services do not initialize review console error messages provided.
            For example: 'Error: data_folder not configured properly, unable to access'

    - Verify the uFrame services are running.
    - If the uFrame services are not running, start them.

    - Verify the OOI UI services are running.
    - If the OOI UI services are not running, start them.
    - Verify the OOI UI services configuration file identifies muframe service host and url correctly.
    - Verify the OOI UI services configuration file variable 'UFRAME_URL_BASE' is same as
            muframe config variable 'uframe_url_root'
    - If the OOI UI services configuration file was modified, ensure the OOI UI services are
            stopped and restarted to affect the changes made.

