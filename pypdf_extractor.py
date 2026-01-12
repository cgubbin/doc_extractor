from pypdf import PdfReader

reader = PdfReader("/Users/kit/Downloads/granted.pdf")

page = reader.pages[1]

print(page.extract_text())

# for i, image_file_object in enumerate(page.images):
#     file_name = "out-image-" + str(i) + "-" + image_file_object.name
#     image_file_object.image.save(file_name)
