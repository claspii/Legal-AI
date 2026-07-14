"""
Default legal templates data and seeding helper.
"""

import json
from sqlalchemy import select
from loguru import logger
from ..models.draft_templates import DraftTemplate

# --- Template 1: Hợp đồng thuê nhà ---
TEMPLATES_DATA = [
    {
        "name": "Hợp đồng thuê nhà",
        "category": "Hợp đồng",
        "description": "Mẫu hợp đồng thuê nhà ở/căn hộ giữa cá nhân với cá nhân, đầy đủ các điều khoản về đặt cọc, thanh toán và quyền nghĩa vụ của hai bên.",
        "placeholders": json.dumps([
            {"key": "landlord_name", "label": "Họ tên Bên Cho Thuê (Bên A)", "type": "text", "default": "Nguyễn Văn A"},
            {"key": "landlord_id", "label": "CMND/CCCD Bên Cho Thuê", "type": "text", "default": ""},
            {"key": "landlord_phone", "label": "Số điện thoại Bên Cho Thuê", "type": "text", "default": ""},
            {"key": "landlord_address", "label": "Địa chỉ Bên Cho Thuê", "type": "text", "default": ""},
            {"key": "tenant_name", "label": "Họ tên Bên Thuê (Bên B)", "type": "text", "default": "Trần Văn B"},
            {"key": "tenant_id", "label": "CMND/CCCD Bên Thuê", "type": "text", "default": ""},
            {"key": "tenant_phone", "label": "Số điện thoại Bên Thuê", "type": "text", "default": ""},
            {"key": "tenant_address", "label": "Địa chỉ Bên Thuê", "type": "text", "default": ""},
            {"key": "property_address", "label": "Địa chỉ nhà cho thuê", "type": "text", "default": ""},
            {"key": "property_area", "label": "Diện tích nhà (m2)", "type": "number", "default": "50"},
            {"key": "rent_amount", "label": "Giá thuê hàng tháng (VNĐ)", "type": "number", "default": "5000000"},
            {"key": "deposit_amount", "label": "Tiền đặt cọc (VNĐ)", "type": "number", "default": "5000000"},
            {"key": "lease_duration", "label": "Thời hạn thuê (tháng)", "type": "number", "default": "12"},
            {"key": "lease_start", "label": "Ngày bắt đầu thuê", "type": "date", "default": "2026-07-01"}
        ], ensure_ascii=False),
        "content": """# CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
---
# HỢP ĐỒNG THUÊ NHÀ Ở

*Căn cứ Bộ luật Dân sự nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2015;*
*Căn cứ Luật Nhà ở năm 2014 và các văn bản hướng dẫn thi hành;*
*Căn cứ nhu cầu và khả năng thực tế của hai bên.*

Hôm nay, ngày {{lease_start}}, tại địa chỉ {{property_address}}, chúng tôi gồm có:

## BÊN CHO THUÊ (BÊN A):
- **Ông/Bà**: {{landlord_name}}
- **CMND/CCCD số**: {{landlord_id}}
- **Địa chỉ thường trú**: {{landlord_address}}
- **Số điện thoại**: {{landlord_phone}}

## BÊN THUÊ (BÊN B):
- **Ông/Bà**: {{tenant_name}}
- **CMND/CCCD số**: {{tenant_id}}
- **Địa chỉ thường trú**: {{tenant_address}}
- **Số điện thoại**: {{tenant_phone}}

Hai bên cùng thống nhất ký kết Hợp đồng thuê nhà ở với các điều khoản cụ thể sau đây:

### ĐIỀU 1: ĐỐI TƯỢNG VÀ NỘI DUNG HỢP ĐỒNG
1. Bên A đồng ý cho Bên B thuê và Bên B đồng ý thuê toàn bộ căn nhà/căn hộ tại địa chỉ: **{{property_address}}**.
2. Diện tích sử dụng: **{{property_area}} m²**.
3. Căn nhà được cho thuê với mục đích: Làm nhà ở cho Bên B và gia đình.

### ĐIỀU 2: THỜI HẠN THUÊ VÀ THỜI GIAN GIAO NHÀ
1. Thời hạn thuê nhà là **{{lease_duration}} tháng**, tính từ ngày **{{lease_start}}**.
2. Hết thời hạn nêu trên, nếu Bên B muốn tiếp tục thuê thì phải báo cho Bên A trước 30 ngày để cùng thỏa thuận ký kết hợp đồng mới.

### ĐIỀU 3: GIÁ THUÊ NHÀ VÀ PHƯƠNG THỨC THANH TOÁN
1. Giá thuê nhà được ấn định là: **{{rent_amount}} VNĐ/tháng** (Bằng chữ: .............................................................. đồng/tháng).
2. Chi phí sử dụng điện sinh hoạt, nước sạch, internet, dịch vụ vệ sinh và quản lý chung cư (nếu có) sẽ do Bên B tự chi trả theo thông báo từ nhà cung cấp dịch vụ.
3. Phương thức thanh toán: Bằng chuyển khoản ngân hàng hoặc tiền mặt, thanh toán vào ngày cuối tháng hoặc trước ngày 05 hàng tháng.

### ĐIỀU 4: TIỀN ĐẶT CỌC
1. Nhằm bảo đảm thực hiện hợp đồng, Bên B giao cho Bên A một khoản tiền đặt cọc là: **{{deposit_amount}} VNĐ** (Bằng chữ: .............................................................. đồng).
2. Số tiền đặt cọc này sẽ được Bên A hoàn trả lại đầy đủ cho Bên B sau khi chấm dứt hợp đồng và Bên B đã thanh toán hết các chi phí liên quan, bàn giao lại nhà nguyên trạng.

### ĐIỀU 5: QUYỀN VÀ NGHĨA VỤ CỦA BÊN A
1. Giao nhà và trang thiết bị cho Bên B đúng thời hạn quy định.
2. Bảo đảm quyền sử dụng nhà độc lập và hợp pháp của Bên B.
3. Bảo dưỡng, sửa chữa lớn cấu trúc ngôi nhà khi có hư hỏng nặng không do lỗi của Bên B.

### ĐIỀU 6: QUYỀN VÀ NGHĨA VỤ CỦA BÊN B
1. Sử dụng nhà đúng mục đích đã thỏa thuận, giữ gìn nhà cửa và trang thiết bị đi kèm.
2. Thanh toán tiền thuê nhà và các chi phí dịch vụ đầy đủ, đúng hạn.
3. Không được tự ý sửa chữa cấu trúc căn nhà hoặc cho bên thứ ba thuê lại (cho thuê phụ) nếu chưa được sự đồng ý bằng văn bản của Bên A.
4. Chấp hành các quy định về an ninh trật tự, phòng cháy chữa cháy tại địa phương.

### ĐIỀU 7: PHƯƠNG THỨC GIẢI QUYẾT TRANH CHẤP
Trong quá trình thực hiện hợp đồng, nếu phát sinh tranh chấp, hai bên cùng nhau bàn bạc giải quyết trên tinh thần thương lượng, hòa giải. Trường hợp không tự giải quyết được, một trong hai bên có quyền khởi kiện ra Tòa án nhân dân có thẩm quyền để giải quyết theo quy định của pháp luật.

### ĐIỀU 8: ĐIỀU KHOẢN THI HÀNH
1. Hợp đồng này có hiệu lực kể từ ngày ký.
2. Hợp đồng được lập thành 02 (hai) bản có giá trị pháp lý như nhau, Bên A giữ 01 bản, Bên B giữ 01 bản để thực hiện.

| BÊN CHO THUÊ (BÊN A) | BÊN THUÊ (BÊN B) |
|:---:|:---:|
| *(Ký, ghi rõ họ tên)* | *(Ký, ghi rõ họ tên)* |
"""
    },
    {
        "name": "Hợp đồng mua bán hàng hóa",
        "category": "Hợp đồng",
        "description": "Mẫu hợp đồng mua bán hàng hóa chuẩn thương mại giữa doanh nghiệp hoặc cá nhân kinh doanh, quy định rõ danh mục sản phẩm, chất lượng, thanh toán và phạt vi phạm.",
        "placeholders": json.dumps([
            {"key": "seller_name", "label": "Tên Bên Bán (Bên A)", "type": "text", "default": "Công ty TNHH A"},
            {"key": "seller_representative", "label": "Người đại diện Bên Bán", "type": "text", "default": "Nguyễn Văn A"},
            {"key": "seller_address", "label": "Địa chỉ Bên Bán", "type": "text", "default": ""},
            {"key": "buyer_name", "label": "Tên Bên Mua (Bên B)", "type": "text", "default": "Công ty TNHH B"},
            {"key": "buyer_representative", "label": "Người đại diện Bên Mua", "type": "text", "default": "Trần Văn B"},
            {"key": "buyer_address", "label": "Địa chỉ Bên Mua", "type": "text", "default": ""},
            {"key": "goods_list", "label": "Danh mục hàng hóa", "type": "text", "default": "Thiết bị văn phòng"},
            {"key": "total_value", "label": "Tổng giá trị hợp đồng (VNĐ)", "type": "number", "default": "100000000"},
            {"key": "delivery_date", "label": "Ngày giao hàng", "type": "date", "default": "2026-08-01"},
            {"key": "delivery_location", "label": "Địa điểm giao nhận", "type": "text", "default": "Văn phòng Bên Mua"}
        ], ensure_ascii=False),
        "content": """# CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
---
# HỢP ĐỒNG MUA BÁN HÀNG HÓA

*Căn cứ Luật Thương mại nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2005;*
*Căn cứ Bộ luật Dân sự nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2015;*
*Căn cứ nhu cầu mua bán hàng hóa của hai bên.*

Hôm nay, ngày ......................., chúng tôi gồm có:

## BÊN BÁN (BÊN A):
- **Tên đơn vị**: {{seller_name}}
- **Địa chỉ trụ sở**: {{seller_address}}
- **Người đại diện theo pháp luật**: Ông/Bà {{seller_representative}}

## BÊN MUA (BÊN B):
- **Tên đơn vị**: {{buyer_name}}
- **Địa chỉ trụ sở**: {{buyer_address}}
- **Người đại diện theo pháp luật**: Ông/Bà {{buyer_representative}}

Hai bên thỏa thuận ký hợp đồng mua bán với nội dung sau:

### ĐIỀU 1: HÀNG HÓA VÀ CHẤT LƯỢNG HÀNG HÓA
1. Tên hàng hóa mua bán: **{{goods_list}}**.
2. Chất lượng hàng hóa: Hàng mới 100%, bảo đảm tiêu chuẩn kỹ thuật của nhà sản xuất.

### ĐIỀU 2: GIÁ TRỊ HỢP ĐỒNG VÀ PHƯƠNG THỨC THANH TOÁN
1. Tổng trị giá hợp đồng: **{{total_value}} VNĐ** (đã bao gồm thuế GTGT).
2. Phương thức thanh toán: Chuyển khoản vào tài khoản ngân hàng của Bên A.
3. Tiến độ thanh toán: Bên B thanh toán tạm ứng 30% sau khi ký hợp đồng và thanh toán 70% còn lại trong vòng 07 ngày sau khi nhận đủ hàng và hóa đơn tài chính hợp lệ.

### ĐIỀU 3: THỜI HẠN VÀ ĐỊA ĐIỂM GIAO NHẬN HÀNG HÓA
1. Thời hạn giao hàng: Đúng hoặc trước ngày **{{delivery_date}}**.
2. Địa điểm giao nhận: **{{delivery_location}}**.
3. Chi phí vận chuyển hàng hóa do Bên A chịu đến địa điểm giao nhận.

### ĐIỀU 4: PHẠT VI PHẠM VÀ BỒI THƯỜNG THIỆT HẠI
1. Nếu Bên A giao hàng chậm trễ, Bên A chịu phạt chậm giao hàng với mức 0,5% giá trị phần hàng hóa chậm giao cho mỗi ngày chậm trễ (tối đa không quá 8% tổng giá trị hợp đồng).
2. Nếu Bên B chậm thanh toán, Bên B chịu lãi chậm thanh toán tính theo lãi suất nợ quá hạn của ngân hàng công bố tại thời điểm phát sinh tranh chấp.

### ĐIỀU 5: GIẢI QUYẾT TRANH CHẤP
Mọi tranh chấp phát sinh sẽ được ưu tiên giải quyết qua thương lượng. Nếu thương lượng không thành công, tranh chấp sẽ được đưa ra Trung tâm Trọng tài Quốc tế Việt Nam (VIAC) hoặc Tòa án kinh tế có thẩm quyền giải quyết.

### ĐIỀU 6: HIỆU LỰC HỢP ĐỒNG
Hợp đồng có hiệu lực kể từ ngày ký và tự động thanh lý khi hai bên hoàn thành xong toàn bộ nghĩa vụ giao nhận hàng và thanh toán. Hợp đồng được lập thành 04 bản tiếng Việt có giá trị như nhau, mỗi bên giữ 02 bản.

| ĐẠI DIỆN BÊN BÁN (BÊN A) | ĐẠI DIỆN BÊN MUA (BÊN B) |
|:---:|:---:|
| *(Ký tên và đóng dấu)* | *(Ký tên và đóng dấu)* |
"""
    },
    {
        "name": "Giấy ủy quyền",
        "category": "Ủy quyền",
        "description": "Mẫu giấy ủy quyền giữa cá nhân với cá nhân hoặc đại diện thực hiện các thủ tục hành chính, pháp lý cụ thể.",
        "placeholders": json.dumps([
            {"key": "authorizer_name", "label": "Tên người ủy quyền", "type": "text", "default": "Nguyễn Văn A"},
            {"key": "authorizer_id", "label": "CMND/CCCD người ủy quyền", "type": "text", "default": ""},
            {"key": "authorizer_address", "label": "Địa chỉ người ủy quyền", "type": "text", "default": ""},
            {"key": "authorized_name", "label": "Tên người được ủy quyền", "type": "text", "default": "Trần Văn B"},
            {"key": "authorized_id", "label": "CMND/CCCD người được ủy quyền", "type": "text", "default": ""},
            {"key": "authorized_address", "label": "Địa chỉ người được ủy quyền", "type": "text", "default": ""},
            {"key": "scope_of_authorization", "label": "Nội dung ủy quyền", "type": "text", "default": "Thực hiện thủ tục đăng ký đất đai"},
            {"key": "authorization_duration", "label": "Thời hạn ủy quyền", "type": "text", "default": "Cho đến khi hoàn thành công việc hoặc có văn bản hủy bỏ"}
        ], ensure_ascii=False),
        "content": """# CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
---
# GIẤY ỦY QUYỀN

- *Căn cứ Bộ luật Dân sự nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2015;*
- *Căn cứ vào các văn bản pháp luật hiện hành.*

Hôm nay, ngày ................................................., tại .............................................................

## I. BÊN ỦY QUYỀN (BÊN A):
- **Họ và tên**: {{authorizer_name}}
- **Ngày sinh**: .................................. **Quốc tịch**: Việt Nam
- **Số CMND/CCCD**: {{authorizer_id}}
- **Địa chỉ thường trú**: {{authorizer_address}}

## II. BÊN ĐƯỢC ỦY QUYỀN (BÊN B):
- **Họ và tên**: {{authorized_name}}
- **Ngày sinh**: .................................. **Quốc tịch**: Việt Nam
- **Số CMND/CCCD**: {{authorized_id}}
- **Địa chỉ thường trú**: {{authorized_address}}

Hai bên thống nhất việc ủy quyền với các nội dung sau:

### ĐIỀU 1: PHẠM VI ỦY QUYỀN
Bên A ủy quyền cho Bên B thực hiện công việc dưới đây:
> **{{scope_of_authorization}}**

Bên B có quyền nhân danh Bên A liên hệ các cơ quan chức năng, ký kết hồ sơ, giấy tờ hành chính liên quan và thực hiện đầy đủ nghĩa vụ phát sinh theo quy định pháp luật để hoàn thành công việc.

### ĐIỀU 2: THỜI HẠN ỦY QUYỀN
Thời hạn ủy quyền là: **{{authorization_duration}}**.

### ĐIỀU 3: QUYỀN VÀ NGHĨA VỤ CỦA CÁC BÊN
1. Bên A có nghĩa vụ cung cấp đầy đủ thông tin, giấy tờ tùy thân liên quan cho Bên B và chịu trách nhiệm về toàn bộ hành vi Bên B thực hiện trong phạm vi ủy quyền.
2. Bên B có trách nhiệm thực hiện công việc cẩn trọng, trung thực, thông báo cho Bên A về tiến độ công việc và không được ủy quyền lại cho bên thứ ba khi chưa được Bên A đồng ý.

### ĐIỀU 4: CAM ĐOAN CỦA CÁC BÊN
Hai bên cam kết chịu trách nhiệm trước pháp luật về mọi thông tin khai báo trong Giấy ủy quyền này và cam kết thực hiện đúng phạm vi ủy quyền đã thỏa thuận.

| BÊN ỦY QUYỀN (BÊN A) | BÊN ĐƯỢC ỦY QUYỀN (BÊN B) |
|:---:|:---:|
| *(Ký, ghi rõ họ tên)* | *(Ký, ghi rõ họ tên)* |
"""
    },
    {
        "name": "Đơn khởi kiện dân sự",
        "category": "Đơn từ",
        "description": "Mẫu đơn khởi kiện vụ án dân sự gửi Tòa án nhân dân cấp huyện theo quy định của Bộ luật Tố tụng Dân sự Việt Nam.",
        "placeholders": json.dumps([
            {"key": "court_name", "label": "Tên Tòa án nhân dân tiếp nhận", "type": "text", "default": "Tòa án nhân dân Quận/Huyện X"},
            {"key": "plaintiff_name", "label": "Tên Người khởi kiện", "type": "text", "default": "Nguyễn Văn A"},
            {"key": "plaintiff_address", "label": "Địa chỉ Người khởi kiện", "type": "text", "default": ""},
            {"key": "plaintiff_phone", "label": "Điện thoại Người khởi kiện", "type": "text", "default": ""},
            {"key": "defendant_name", "label": "Tên Người bị kiện", "type": "text", "default": "Trần Văn B"},
            {"key": "defendant_address", "label": "Địa chỉ Người bị kiện", "type": "text", "default": ""},
            {"key": "defendant_phone", "label": "Điện thoại Người bị kiện", "type": "text", "default": ""},
            {"key": "lawsuit_facts", "label": "Tóm tắt sự việc tranh chấp", "type": "text", "default": "Bị đơn vay nợ quá hạn nhưng không trả..."},
            {"key": "lawsuit_claims", "label": "Các yêu cầu khởi kiện giải quyết", "type": "text", "default": "Yêu cầu bị đơn thanh toán số nợ gốc và lãi..."},
            {"key": "evidence_list", "label": "Danh mục tài liệu chứng cứ kèm theo", "type": "text", "default": "1. Hợp đồng vay tiền; 2. Giấy biên nhận nhận tiền."}
        ], ensure_ascii=False),
        "content": """# CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
---
## ĐƠN KHỞI KIỆN

*Kính gửi:* **{{court_name}}**

### NGƯỜI KHỞI KIỆN:
- **Họ và tên**: {{plaintiff_name}}
- **Địa chỉ cư trú**: {{plaintiff_address}}
- **Số điện thoại**: {{plaintiff_phone}}

### NGƯỜI BỊ KIỆN:
- **Họ và tên**: {{defendant_name}}
- **Địa chỉ cư trú**: {{defendant_address}}
- **Số điện thoại**: {{defendant_phone}}

### NỘI DUNG VÀ LÝ DO KHỞI KIỆN:
{{lawsuit_facts}}

Vì những lý do nêu trên, tôi làm đơn này đề nghị Tòa án giải quyết các vấn đề sau đối với Bị đơn:
{{lawsuit_claims}}

### DANH MỤC TÀI LIỆU, CHỨNG CỨ GỬI KÈM ĐƠN:
{{evidence_list}}

Tôi cam đoan những lời khai trong đơn hoàn toàn đúng sự thật.

**NGƯỜI KHỞI KIỆN**
*(Ký, ghi rõ họ tên)*
"""
    },
    {
        "name": "Thỏa thuận bảo mật thông tin (NDA)",
        "category": "Hợp đồng",
        "description": "Mẫu thỏa thuận bảo mật thông tin (Non-Disclosure Agreement) giữa đối tác kinh doanh hoặc doanh nghiệp với người lao động.",
        "placeholders": json.dumps([
            {"key": "disclosing_party", "label": "Bên tiết lộ thông tin (Bên A)", "type": "text", "default": "Công ty Cổ phần X"},
            {"key": "disclosing_representative", "label": "Đại diện Bên A", "type": "text", "default": "Nguyễn Văn A"},
            {"key": "receiving_party", "label": "Bên nhận thông tin (Bên B)", "type": "text", "default": "Công ty TNHH Y / Cá nhân B"},
            {"key": "receiving_representative", "label": "Đại diện Bên B", "type": "text", "default": "Trần Văn B"},
            {"key": "confidential_info_definition", "label": "Định nghĩa thông tin bảo mật", "type": "text", "default": "Thông tin kỹ thuật, thông tin tài chính và kế hoạch kinh doanh"},
            {"key": "duration_of_confidentiality", "label": "Thời hạn bảo mật", "type": "text", "default": "03 năm kể từ ngày chấm dứt quan hệ hợp tác"}
        ], ensure_ascii=False),
        "content": """# CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
## Độc lập - Tự do - Hạnh phúc
---
# THỎA THUẬN BẢO MẬT THÔNG TIN (NDA)

*Căn cứ Bộ luật Dân sự nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2015;*
*Căn cứ Luật Sở hữu trí tuệ nước Cộng hòa Xã hội Chủ nghĩa Việt Nam năm 2005 sửa đổi, bổ sung;*
*Nhằm bảo mật các thông tin trao đổi phục vụ mục đích hợp tác giữa hai bên.*

Hôm nay, ngày ......................., Thỏa thuận này được lập giữa:

## BÊN TIẾT LỘ (BÊN A):
- **Tên tổ chức**: {{disclosing_party}}
- **Người đại diện**: Ông/Bà {{disclosing_representative}}

## BÊN NHẬN (BÊN B):
- **Tên tổ chức/cá nhân**: {{receiving_party}}
- **Người đại diện (nếu có)**: Ông/Bà {{receiving_representative}}

Hai bên cam kết thực hiện đúng các điều khoản dưới đây:

### ĐIỀU 1: THÔNG TIN BẢO MẬT
Thông tin bảo mật bao gồm bất kỳ thông tin nào được Bên A cung cấp cho Bên B có chứa nhãn "Bảo mật", hoặc thông tin được trao đổi trực tiếp/gián tiếp dưới các hình thức: dữ liệu số, tài liệu thiết kế, báo cáo tài chính, và các loại tài liệu sau:
> **{{confidential_info_definition}}**

### ĐIỀU 2: TRÁCH NHIỆM BẢO MẬT CỦA BÊN B
1. Chỉ sử dụng thông tin bảo mật cho mục đích thực hiện dự án hợp tác giữa hai bên.
2. Không tiết lộ thông tin bảo mật cho bất kỳ bên thứ ba nào khi chưa có sự chấp thuận bằng văn bản của Bên A.
3. Áp dụng các biện pháp an ninh tối thiểu ngang bằng với biện pháp Bên B bảo vệ tài sản trí tuệ của chính mình để tránh làm thất thoát thông tin.

### ĐIỀU 3: HIỆU LỰC VÀ THỜI HẠN BẢO MẬT
Hiệu lực bảo mật của thỏa thuận kéo dài trong suốt quá trình hợp tác và **{{duration_of_confidentiality}}** sau khi chấm dứt hợp đồng hợp tác.

### ĐIỀU 4: PHẠT VI PHẠM
Trường hợp Bên B để rò rỉ thông tin bảo mật gây tổn hại kinh tế cho Bên A, Bên B chịu phạt vi phạm thỏa thuận này với số tiền tương ứng thiệt hại thực tế phát sinh và có trách nhiệm bồi thường toàn bộ thiệt hại đó.

| ĐẠI DIỆN BÊN TIẾT LỘ (BÊN A) | ĐẠI DIỆN BÊN NHẬN (BÊN B) |
|:---:|:---:|
| *(Ký và đóng dấu)* | *(Ký và đóng dấu)* |
"""
    }
]


async def seed_templates(db):
    """Seed the template table if it is empty."""
    try:
        # Check if templates table has data
        result = await db.execute(select(DraftTemplate))
        existing = result.scalars().first()
        if existing:
            logger.info("Draft templates already seeded.")
            return

        logger.info("Seeding draft templates into SQLite database...")
        for t_data in TEMPLATES_DATA:
            template = DraftTemplate(
                name=t_data["name"],
                category=t_data["category"],
                description=t_data["description"],
                placeholders=t_data["placeholders"],
                content=t_data["content"]
            )
            db.add(template)
        await db.commit()
        logger.info("Successfully seeded draft templates.")
    except Exception as e:
        logger.error(f"Error seeding draft templates: {e}")
        await db.rollback()
