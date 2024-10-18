import datetime
import logging
import re

from eve.methods.get import get_internal
from lxml import etree, html as lxml_html
from lxml.etree import SubElement

import superdesk
from superdesk.core.web import EndpointGroup
from superdesk.core.types import Request
from superdesk.core import get_app_config
from superdesk.flask import url_for, Response
from superdesk.utc import utcnow
from superdesk.etree import to_string

from newsroom.core import get_current_wsgi_app
from newsroom.auth.utils import get_company_or_none_from_request
from newsroom.news_api.utils import check_association_permission
from newsroom.products.products import get_products_by_company

logger = logging.getLogger(__name__)
atom_endpoints = EndpointGroup("atom", __name__)


@atom_endpoints.endpoint("atom", methods=["GET"], auth=False)
async def get_atom(request: Request):
    def _format_date(date):
        iso8601 = date.isoformat()
        if date.tzinfo:
            return iso8601
        return iso8601 + "Z"

    def _format_update_date(date):
        DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
        return date.strftime(DATETIME_FORMAT) + "Z"

    auth = get_current_wsgi_app().auth
    if not auth.authorized([], None, request.method):
        return auth.authenticate()

    XML_ROOT = '<?xml version="1.0" encoding="UTF-8"?>'

    _message_nsmap = {
        None: "http://www.w3.org/2005/Atom",
        "dcterms": "http://purl.org/dc/terms/",
        "media": "http://search.yahoo.com/mrss/",
        "mi": "http://schemas.ingestion.microsoft.com/common/",
    }

    #    feed = etree.Element('feed', attrib={'lang': 'en-us'}, nsmap=_message_nsmap)
    feed = etree.Element("feed", nsmap=_message_nsmap)
    site_name = get_app_config("SITE_NAME")
    SubElement(feed, "title").text = etree.CDATA("{} Atom Feed".format(site_name))
    SubElement(feed, "updated").text = _format_update_date(utcnow())
    SubElement(SubElement(feed, "author"), "name").text = site_name
    SubElement(feed, "id").text = url_for("atom.get_atom", _external=True)
    SubElement(
        feed,
        "link",
        attrib={"href": url_for("atom.get_atom", _external=True), "rel": "self"},
    )

    # TODO-ASYNC: replace once the service is ready
    response = await get_internal("news/search")
    company = get_company_or_none_from_request(None)
    products = get_products_by_company(company.to_dict(context={"use_objectid": True}) if company else None)

    for item in response[0].get("_items"):
        try:
            # TODO-ASYNC: revisit when items are made async
            complete_item = superdesk.get_resource_service("items").find_one(req=None, _id=item.get("_id"))
            if not complete_item:
                continue

            # If featuremedia is not allowed for the company don't add the item
            if ((complete_item.get("associations") or {}).get("featuremedia") or {}).get("renditions"):
                if not check_association_permission(complete_item, products):
                    continue

            entry = SubElement(feed, "entry")

            # If the item has any parents we use the id of the first, this should be constant throught the update
            # history
            if complete_item.get("ancestors") and len(complete_item.get("ancestors")):
                SubElement(entry, "id").text = complete_item.get("ancestors")[0]
            else:
                SubElement(entry, "id").text = str(complete_item.get("_id"))

            SubElement(entry, "title").text = etree.CDATA(complete_item.get("headline"))
            SubElement(entry, "published").text = _format_date(complete_item.get("firstpublished"))
            SubElement(entry, "updated").text = _format_update_date(complete_item.get("versioncreated"))
            SubElement(
                entry,
                "link",
                attrib={
                    "rel": "self",
                    "href": url_for(
                        "news/item.get_item",
                        item_id=item.get("_id"),
                        format="TextFormatter",
                        _external=True,
                    ),
                },
            )
            if complete_item.get("byline"):
                SubElement(SubElement(entry, "author"), "name").text = complete_item.get("byline")

            if complete_item.get("pubstatus") == "usable":
                SubElement(
                    entry, etree.QName(_message_nsmap.get("dcterms"), "valid")
                ).text = "start={}; end={}; scheme=W3C-DTF".format(
                    _format_date(utcnow()),
                    _format_date(utcnow() + datetime.timedelta(days=30)),
                )
            else:
                # in effect a kill set the end date into the past
                SubElement(
                    entry, etree.QName(_message_nsmap.get("dcterms"), "valid")
                ).text = "start={}; end={}; scheme=W3C-DTF".format(
                    _format_date(utcnow()),
                    _format_date(utcnow() - datetime.timedelta(days=30)),
                )

            categories = [{"name": s.get("name")} for s in complete_item.get("service", [])]
            for category in categories:
                SubElement(entry, "category", attrib={"term": category.get("name")})

            SubElement(entry, "summary").text = etree.CDATA(complete_item.get("description_text", ""))

            # If there are any image embeds then reset the source to a Newshub asset
            html_updated = False
            regex = r" EMBED START Image {id: \"editor_([0-9]+)"
            root_elem = lxml_html.fromstring(complete_item.get("body_html", "<html></html>"))
            comments = root_elem.xpath("//comment()")

            for comment in comments:
                if "EMBED START Image" in comment.text:
                    m = re.search(regex, comment.text)
                    # Assumes the sibling of the Embed Image comment is the figure tag containing the image
                    figure_elem = comment.getnext()
                    if figure_elem is not None and figure_elem.tag == "figure":
                        imgElem = figure_elem.find("./img")
                        if imgElem is not None and m and m.group(1):
                            embed_id = "editor_" + m.group(1)
                            src = complete_item.get("associations").get(embed_id).get("renditions").get("16-9")
                            if src:
                                imgElem.attrib["src"] = url_for(
                                    "assets.get_item",
                                    asset_id=src.get("media"),
                                    _external=True,
                                    _scheme="https",
                                )
                                html_updated = True
            if html_updated:
                complete_item["body_html"] = to_string(root_elem, method="html")

            SubElement(entry, "content", attrib={"type": "html"}).text = etree.CDATA(complete_item.get("body_html", ""))

            if ((complete_item.get("associations") or {}).get("featuremedia") or {}).get("renditions"):
                image = (
                    ((complete_item.get("associations") or {}).get("featuremedia") or {}).get("renditions").get("16-9")  # type: ignore
                )
                if not image or not complete_item:
                    continue
                metadata = (complete_item.get("associations") or {}).get("featuremedia") or {}

                url = url_for("assets.get_item", _external=True, asset_id=image.get("media"))
                media = SubElement(
                    entry,
                    etree.QName(_message_nsmap.get("media"), "content"),
                    attrib={
                        "url": url,
                        "type": image.get("mimetype"),
                        "medium": "image",
                    },
                )

                SubElement(media, etree.QName(_message_nsmap.get("media"), "credit")).text = metadata.get("byline")
                SubElement(media, etree.QName(_message_nsmap.get("media"), "title")).text = metadata.get(
                    "description_text"
                )
                SubElement(media, etree.QName(_message_nsmap.get("media"), "text")).text = metadata.get("body_text")
                focr = SubElement(media, etree.QName(_message_nsmap.get("mi"), "focalRegion"))
                SubElement(focr, etree.QName(_message_nsmap.get("mi"), "x1")).text = str(image.get("poi").get("x"))
                SubElement(focr, etree.QName(_message_nsmap.get("mi"), "x2")).text = str(image.get("poi").get("x"))
                SubElement(focr, etree.QName(_message_nsmap.get("mi"), "y1")).text = str(image.get("poi").get("y"))
                SubElement(focr, etree.QName(_message_nsmap.get("mi"), "y2")).text = str(image.get("poi").get("y"))
        except Exception as ex:
            logger.exception("processing {} - {}".format(item.get("_id"), ex))

    return Response(
        XML_ROOT + etree.tostring(feed, pretty_print=True).decode("utf-8"),
        mimetype="application/atom+xml",
    )