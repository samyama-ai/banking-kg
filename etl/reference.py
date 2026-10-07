"""Reference data supplied alongside the bank's request, not requested from the bank.

MCC: merchant category code descriptions from the public ISO 18245 list, for
the codes the synthetic transactions use.
"""

MCC = {
    "4111": "Commuter transport", "4121": "Taxicabs and limousines", "4511": "Airlines",
    "4814": "Telecommunication services", "4900": "Utilities: electric, gas, water",
    "5200": "Home supply warehouse stores", "5251": "Hardware stores", "5300": "Wholesale clubs",
    "5310": "Discount stores", "5311": "Department stores", "5411": "Grocery stores and supermarkets",
    "5462": "Bakeries", "5499": "Miscellaneous food stores", "5511": "Car and truck dealers",
    "5541": "Service stations", "5542": "Automated fuel dispensers", "5691": "Clothing stores",
    "5732": "Electronics stores", "5812": "Restaurants", "5813": "Bars and drinking places",
    "5814": "Fast food restaurants", "5912": "Drug stores and pharmacies", "5942": "Book stores",
    "5968": "Subscription services", "5995": "Pet shops and supplies", "5999": "Specialty retail",
    "7011": "Hotels and lodging", "7230": "Barber and beauty shops", "7538": "Auto service shops",
    "7832": "Movie theaters", "8011": "Doctors", "8062": "Hospitals", "8099": "Medical services",
    "8211": "Schools", "8220": "Colleges and universities",
}
