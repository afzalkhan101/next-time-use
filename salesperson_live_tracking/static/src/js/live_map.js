odoo.define('salesperson_tracking.map_live', function(require){
    "use strict";
    var AbstractAction = require('web.AbstractAction');
    var rpc = require('web.rpc');

    var LiveMap = AbstractAction.extend({
        template: 'LiveMapTemplate',
        start: async function(){
            this.map = L.map(this.$el[0]).setView([23.8103, 90.4125], 12); // Dhaka Example
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
            }).addTo(this.map);

            this.markers = {};
            await this.updateMarkers();
            setInterval(this.updateMarkers.bind(this), 5000); 
        },
        updateMarkers: async function(){
            var self = this;
            const res = await rpc.query({
                model: 'salesperson.tracker',
                method: 'search_read',
                fields: ['user_id','latitude','longitude','tracking_status'],
                domain: [('tracking_status','=','live')],
            });

            res.forEach(function(record){
                var id = record.user_id[0];
                if(self.markers[id]){
                    self.markers[id].setLatLng([record.latitude, record.longitude]);
                } else {
                    var marker = L.marker([record.latitude, record.longitude]).addTo(self.map)
                        .bindPopup(record.user_id[1]);
                    self.markers[id] = marker;
                }
            });
        }
    });

    return LiveMap;
});