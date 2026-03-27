# nlp-research-trend-analysis
"A RAG-Based Approach for Analyzing Research Trends in Academic Publications" is my final year research project. 

## The Research Problem
The research problem that is beign addressed through this research project is the need for an automated system to analyse the trend in research topics.
The rapid expansion of the domain of academic research with thousands of papers being published daily across multiple disciplines, presents a challenge for researchers and institutions in identifying emerging trends and shifts in knowledge areas. 
Traditional manual reviews are time-consuming and often fail to capture timely insights. Furthermore, the existing trend analysis were done only for a specific domain. Hence, there arises a need for an automated approache to detect and present research trends effectively.

## Data - Sample Data and Actual data
Due to copyright restrictions, full datasets are not included.

## Dataset Source

## Tools
Metadata Extraction: OpenAlex API, Gemini API (Google AI Studio), 
Analysis: Google Colab

## Methodoly
Methodology can be mapped into three main phases as metadata extraction, research paper analysis, and visualization.

# Metadata Extraction
    First method was to extract metadata such as DOI, arXiv ID, and Title, then look up on OpenAlex using it's API. To create the extraction pipeline, first, 10 research papers in pdf format were used as a sample set.
During the extraction, most of the papers did not contain DOI, while arXiv and title had noise. The arXiv ID had to be normalized before looking up on OpenAlex. Extracted titles contained other metadata such as author names and noisy data such as header and footer. Therefore, titles had to be extracted omitting author names and skipping header or footer too.
Results: 
Even after all the preprocessings while extraction and before looking up on OpenAlex, 4 out of 10 paper titles were recognized incorrectly. For example, when the extraction output title as "Reinforcement Learning Teachers of Test Time Scaling", OpenAlex presented title as "The qualitative content analysis process", and retrieved it's metadata.

    In the second method the first page of the each paper were converted into an image (pdf_to_image.py). Then the metadata was extracted from the image using Gemini API (gemini_extract.py). Gemini API key was acquired from the Google AI Studio. A prompt (prompt.py) was used for retrieving the metadata.

The disadvantage was that it has limits such as requests per a minute (RPM), tokens for a minute (TPM) and requests per a day (RPD), making it difficult to extract metadata from a large number of papers. Every time it posed an error - "429 RESOURCE_EXHAUSTED" to be specific.

In test_code.py one paper was tested with gemini_2.5_flash and was a success. As the request per a minute was 5, an interval of 12s between 2 request had to be made. And because the request per a day is 20 in free tier, only 20 papers could be tested in a day. Additionally, as the tokens per a minute is 250k, number of words on the prompt had to be reconsidered.

Results: 

In this metadata ectraction method the versions selected were either did not excel in extracting metadata or did not belong in free tier (e.g. gemini-2.5-flash-image). Therefore, this method is halted for futher analysis in the future.

    In the third method, GeneRation Of BIbliographic Data (GROBID) was used for extracting metadata. It is an open-source machine learning–based library designed to extract, structure, and normalize information from scholarly documents, primarily PDFs. 

First Docker Descktop was installed. Then, the GROBID image was pulled which includes Java, ML models, and GROBID server. Next, GROBID server was started. After setting up the environment, it was tested for one sample pdf. The output observation included that the names of authors were extracted in the format of [Lastname, FirstName]. The title, abstract, and keywords did not have apperant diviation from the actual metadata.
Next, it was tested for a set of 10 PDFs. For that, dependancies for lxml and tqdm had to be installed. 

Limitations of automated metadata extraction in GROBID is, it may fail to produce valid TEI XML for certain PDFs, requiring error handling and fallback mechanisms. 
There is also the limitation of full-text parsing, where it has taken the authors of the referenced papers as authors of the paper. To overcome this limitation, fulltext endpoint had to be used while extracting authors only from <teiHeader>

Next observation was that universitie/institution names were extracted as author names and some author names were missing. Therefore, an author name cleaning mechanism had to be used. Even after the fix, GROBID still extracted an institution name (UC Berkeley) as an author name and one author name was missing in few records. 

Keywords included stopwords and were combined with sentences, especially the last keyword. To fix this, following steps were taken: Split keywords by commas or semicolons (if available), remove stopwords like “and”, “full form”, “abbreviations”, keep only short phrases (<=5 words) for keyword. After the fixes were applied some keywords were still missing, specially the ones that had stopwords and were combined with sectences. Additionally, in one paper, words on an image were extracted as keywords.
 

After careful consideration, a decision was made to ignore user-defined keywords. The reason being that some papers does not contain user-defined keywords. Furthermore, if keywords were to be taken in different ways, it might create variation. And most of the time, for topic modeling /trend analysis, the title and abstract are used instead of user-defined keywords, especially the models that are being considered in this research project, such as LDA, NMF, and BERT and its versions.
Another consideration is adding the publication year. In arXiv files, the year is parsed from the file name. Although arXiv files are saved with the month and year, other files are not. Therefore this had to be taken into consideration.
