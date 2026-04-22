import base64
from odoo import http
from odoo.http import request

class SalespersonTrackingController(http.Controller):

    @http.route('/salesperson_tracking/save_photo', type='json', auth='user', methods=['POST'], csrf=False)
    def save_photo(self, image_data='', filename=None, **kwargs):

        try:
            if not image_data:
                return {'success': False, 'message': 'No image data received'}

            filename = filename or f'salesperson_photo_{request.env.uid}.jpg'
         
            image_b64 = image_data.split(',', 1)[1] if ',' in image_data else image_data

            tracker = request.env['salesperson.tracker'].sudo().search(
                [('user_id', '=', request.env.uid)], limit=1
            )




            if not tracker:
                return {'success': False, 'message': 'Tracker record not found for this user'}

            attachment = request.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': image_b64,
                'mimetype': 'image/jpeg',
                'res_model': 'salesperson.tracker',
                'res_id': tracker.id,
                'description': f'Field photo — {request.env.user.name}',
            })


            print("###########$#$#4",attachment)

            tracker.message_post(
                body="Attachment uploaded via API",
                attachment_ids=[attachment.id]
            )


            return {
                'success': True,
                'attachment_id': attachment.id,
                'message': 'Photo saved successfully',
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}