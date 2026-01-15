import sys
import pymupdf

if __name__ == "__main__":
    """Only for debugging purposes, currently.

    Draw red borders around the returned text bboxes and insert
    the bbox number.
    Then save the file under the name "input-blocks.pdf".
    """

    # get the file name
    filename = sys.argv[1]

    # check if footer margin is given
    if len(sys.argv) > 2:
        footer_margin = int(sys.argv[2])
    else:  # use default vaue
        footer_margin = 50

    # check if header margin is given
    if len(sys.argv) > 3:
        header_margin = int(sys.argv[3])
    else:  # use default vaue
        header_margin = 50

    # open document
    doc = pymupdf.open(filename)

    # iterate over the pages
    ii = 0
    for page in doc:
        print(f"Page {ii + 1}")
        (x0, y0, x1, y1) = page.mediabox

        left_col_mediabox = pymupdf.Rect(
            x0, y0 - header_margin, x0 + (x1 - x0) / 2, y1 + footer_margin
        )

        right_col_mediabox = pymupdf.Rect(
            x0 + (x1 - x0) / 2, y0 - header_margin, x1, y1 + footer_margin
        )

        if ii == 0:
            left_text = page.get_textbox(left_col_mediabox)
            right_text = page.get_textbox(right_col_mediabox)
            print("=== Left Column ===")
            print(left_text)
            print("=== Right Column ===")
            print(right_text)
        # print(page.get_text(sort=True))
        ii += 1
